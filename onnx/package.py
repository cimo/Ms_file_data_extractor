import sys
import io
import struct
import hashlib
import base64
import xml.etree.ElementTree
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

sys.dont_write_bytecode = True

# Source
from helper import xmlNodeTag, messageEncryption, messagePasswordRequired, messagePasswordWrong

class Package:
    def _sectorByte(self, byteList, sizeSector, sector):
        return byteList[(sector + 1) * sizeSector:(sector + 2) * sizeSector]

    def _chainList(self, tableList, sector):
        resultList = []

        while sector < len(tableList) and len(resultList) < len(tableList):
            resultList.append(sector)

            sector = tableList[sector]

        return resultList

    def _streamObject(self, byteList):
        resultObject = {}

        sizeSector = 1 << struct.unpack_from("<H", byteList, 30)[0]
        sizeMini = 1 << struct.unpack_from("<H", byteList, 32)[0]

        countTable, sectorDirectory = struct.unpack_from("<II", byteList, 44)
        sizeCutoff, sectorMini, countMini, sectorExtra, countExtra = struct.unpack_from("<IIIII", byteList, 56)

        sectorTableList = list(struct.unpack_from("<109I", byteList, 76))

        for a in range(countExtra):
            valueList = struct.unpack(f"<{int(sizeSector / 4)}I", self._sectorByte(byteList, sizeSector, sectorExtra))

            sectorTableList += valueList[0:len(valueList) - 1]

            sectorExtra = valueList[len(valueList) - 1]

        tableList = []

        for a in range(countTable):
            tableList += struct.unpack(f"<{int(sizeSector / 4)}I", self._sectorByte(byteList, sizeSector, sectorTableList[a]))

        directoryByteList = b"".join(self._sectorByte(byteList, sizeSector, sector) for sector in self._chainList(tableList, sectorDirectory))
        miniTableByteList = b"".join(self._sectorByte(byteList, sizeSector, sector) for sector in self._chainList(tableList, sectorMini))

        miniTableList = struct.unpack(f"<{int(len(miniTableByteList) / 4)}I", miniTableByteList)

        miniByteList = b""

        for a in range(int(len(directoryByteList) / self.sizeEntry)):
            entryByteList = directoryByteList[a * self.sizeEntry:(a + 1) * self.sizeEntry]

            sizeName = struct.unpack_from("<H", entryByteList, 64)[0]

            sectorStart = struct.unpack_from("<I", entryByteList, 116)[0]
            sizeStream = struct.unpack_from("<Q", entryByteList, 120)[0] % (1 << 32 if sizeSector == self.sizeSectorSmall else 1 << 64)

            name = entryByteList[0:max(0, sizeName - 2)].decode("utf-16-le")

            if entryByteList[66] == self.typeRoot:
                miniByteList = b"".join(self._sectorByte(byteList, sizeSector, sector) for sector in self._chainList(tableList, sectorStart))
            elif entryByteList[66] == self.typeStream and sizeStream < sizeCutoff:
                resultObject[name] = b"".join(miniByteList[sector * sizeMini:(sector + 1) * sizeMini] for sector in self._chainList(miniTableList, sectorStart))[0:sizeStream]
            elif entryByteList[66] == self.typeStream:
                resultObject[name] = b"".join(self._sectorByte(byteList, sizeSector, sector) for sector in self._chainList(tableList, sectorStart))[0:sizeStream]

        return resultObject

    def _sizeFit(self, byteList, size):
        return (byteList + bytes([self.bytePad]) * size)[0:size]

    def _blockDecrypt(self, key, mode, byteList):
        decryptor = Cipher(algorithms.AES(key), mode).decryptor()

        return decryptor.update(byteList + bytes(-len(byteList) % self.sizeBlock)) + decryptor.finalize()

    def _hashSpin(self, nameHash, salt, password, count):
        result = hashlib.new(nameHash, salt + password.encode("utf-16-le")).digest()

        for a in range(count):
            result = hashlib.new(nameHash, struct.pack("<I", a) + result).digest()

        return result

    def _agileKey(self, nodeObject, password):
        attributeObject = nodeObject["encryptedKey"].attrib

        nameHash = attributeObject["hashAlgorithm"].casefold()

        salt = base64.b64decode(attributeObject["saltValue"])

        sizeKey = int(int(attributeObject["keyBits"]) / 8)

        hashBase = self._hashSpin(nameHash, salt, password, int(attributeObject["spinCount"]))

        vector = self._sizeFit(salt, int(attributeObject["blockSize"]))

        valueList = []

        for a in range(len(self.blockKeyList)):
            key = self._sizeFit(hashlib.new(nameHash, hashBase + self.blockKeyList[a]).digest(), sizeKey)

            valueList.append(self._blockDecrypt(key, modes.CBC(vector), base64.b64decode(attributeObject[self.blockNameList[a]])))

        hashInput = hashlib.new(nameHash, valueList[0][0:int(attributeObject["saltSize"])]).digest()

        return valueList[2][0:sizeKey] if hashInput == valueList[1][0:len(hashInput)] else b""

    def _agileDecrypt(self, streamObject, password):
        rootNode = xml.etree.ElementTree.fromstring(streamObject[self.nameInformation][8:])

        nodeObject = {xmlNodeTag(node): node for node in rootNode.iter() if xmlNodeTag(node) in ["keyData", "encryptedKey"]}

        if len(nodeObject) < 2 or len([node for node in nodeObject.values() if node.attrib.get("cipherAlgorithm", "") != self.nameCipher or node.attrib.get("cipherChaining", "") != self.nameChain or node.attrib.get("hashAlgorithm", "").casefold() not in hashlib.algorithms_available]) > 0:
            return {"message": messageEncryption, "byteList": b""}

        key = self._agileKey(nodeObject, password)

        if key == b"":
            return {"message": messagePasswordWrong, "byteList": b""}

        attributeObject = nodeObject["keyData"].attrib

        salt = base64.b64decode(attributeObject["saltValue"])

        packageByteList = streamObject[self.namePackage]

        resultList = []

        for a in range(8, len(packageByteList), self.sizeSegment):
            vector = self._sizeFit(hashlib.new(attributeObject["hashAlgorithm"].casefold(), salt + struct.pack("<I", int((a - 8) / self.sizeSegment))).digest(), int(attributeObject["blockSize"]))

            resultList.append(self._blockDecrypt(key, modes.CBC(vector), packageByteList[a:a + self.sizeSegment]))

        return {"message": "", "byteList": b"".join(resultList)[0:struct.unpack_from("<Q", packageByteList, 0)[0]]}

    def _standardDecrypt(self, streamObject, password):
        informationByteList = streamObject[self.nameInformation]

        sizeHeader = struct.unpack_from("<I", informationByteList, 8)[0]

        algorithm, algorithmHash, sizeKeyBit = struct.unpack_from("<III", informationByteList, 20)

        if algorithm not in self.algorithmAesList or algorithmHash not in self.algorithmHashList:
            return {"message": messageEncryption, "byteList": b""}

        offset = 12 + sizeHeader

        salt = informationByteList[offset + 4:offset + 20]

        hashBase = hashlib.sha1(self._hashSpin("sha1", salt, password, self.countSpinStandard) + struct.pack("<I", 0)).digest()

        key = b"".join(hashlib.sha1(bytes(byte ^ pad for byte in hashBase) + bytes([pad]) * (64 - len(hashBase))).digest() for pad in self.bytePadStandardList)[0:int(sizeKeyBit / 8)]

        verifier = self._blockDecrypt(key, modes.ECB(), informationByteList[offset + 20:offset + 36])
        verifierHash = self._blockDecrypt(key, modes.ECB(), informationByteList[offset + 40:offset + 72])

        if hashlib.sha1(verifier).digest() != verifierHash[0:20]:
            return {"message": messagePasswordWrong, "byteList": b""}

        packageByteList = streamObject[self.namePackage]

        return {"message": "", "byteList": self._blockDecrypt(key, modes.ECB(), packageByteList[8:])[0:struct.unpack_from("<Q", packageByteList, 0)[0]]}

    def _decrypt(self, streamObject, password):
        versionMajor, versionMinor = struct.unpack_from("<HH", streamObject[self.nameInformation], 0)

        if versionMajor == 4 and versionMinor == 4:
            return self._agileDecrypt(streamObject, password)

        if versionMinor == 2:
            return self._standardDecrypt(streamObject, password)

        return {"message": messageEncryption, "byteList": b""}

    def execute(self, pathInput, password):
        with open(pathInput, "rb") as file:
            byteList = file.read(len(self.signature))

            if byteList == self.signature:
                byteList += file.read()

        if byteList[0:len(self.signature)] != self.signature:
            return {"message": "", "file": pathInput}

        streamObject = self._streamObject(byteList)

        if self.nameInformation not in streamObject or self.namePackage not in streamObject:
            return {"message": "", "file": pathInput}

        resultObject = self._decrypt(streamObject, self.passwordDefault)

        if resultObject["message"] == messagePasswordWrong and password != "":
            resultObject = self._decrypt(streamObject, password)
        elif resultObject["message"] == messagePasswordWrong:
            resultObject["message"] = messagePasswordRequired

        return {"message": resultObject["message"], "file": io.BytesIO(resultObject["byteList"])}

    def __init__(self):
        self.signature = bytes([208, 207, 17, 224, 161, 177, 26, 225])

        self.sizeEntry = 128
        self.sizeSectorSmall = 512
        self.sizeBlock = 16
        self.sizeSegment = 4096

        self.typeStream = 2
        self.typeRoot = 5

        self.nameInformation = "EncryptionInfo"
        self.namePackage = "EncryptedPackage"
        self.nameCipher = "AES"
        self.nameChain = "ChainingModeCBC"

        self.passwordDefault = "VelvetSweatshop"

        self.bytePad = 54
        self.bytePadStandardList = [54, 92]

        self.countSpinStandard = 50000

        self.algorithmAesList = [26126, 26127, 26128]
        self.algorithmHashList = [0, 32772]

        self.blockNameList = ["encryptedVerifierHashInput", "encryptedVerifierHashValue", "encryptedKeyValue"]
        self.blockKeyList = [bytes([254, 167, 210, 118, 59, 75, 158, 121]), bytes([215, 170, 15, 109, 48, 97, 52, 78]), bytes([20, 110, 11, 231, 171, 172, 208, 214])]
