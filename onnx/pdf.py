import sys
import icu
import fontTools.agl
import math
import zlib
import base64
import codecs
import hashlib
import re
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

sys.dont_write_bytecode = True

# Source
from helper import spacelessCheck, whitespaceCheck, boxFromPointList, characterNormalize, ideographPageResolve

def mergeText(elementList):
    resultList = []

    current = None
    pendingList = []

    for a in range(len(elementList)):
        element = elementList[a]

        if element["type"] != "text":
            if current is None:
                resultList.append(element)
            else:
                pendingList.append(element)
        elif current is None:
            current = element
        else:
            size = current["fontSize"] if current.get("fontSize") is not None else 0
            elementSize = element["fontSize"] if element.get("fontSize") is not None else 0

            if current["isVertical"]:
                gap = element["y0"] - current["y1"]

                isSameLine = abs(element["x0"] - current["x0"]) <= size * 0.6
            else:
                gap = element["x0"] - current["x1"]

                isSameLine = abs(element["y0"] - current["y0"]) <= size * 0.6

            isSameLine = isSameLine and current["isVertical"] == element["isVertical"]
            isCompatibleSize = elementSize >= size * 0.45 and elementSize <= size * 1.4
            isClose = gap >= -size * 0.3 and gap <= size * 0.6

            if isClose and gap >= size * 0.4 and gapOccupiedCheck(current, elementList, element, size):
                isClose = False

            if isSameLine and isCompatibleSize and isClose:
                previousText = current["text"] if current.get("text") is not None else ""
                elementText = element["text"] if element.get("text") is not None else ""
                isSpace = gap > size * 0.15 and whitespaceCheck(previousText[-1:]) == False and whitespaceCheck(elementText[0:1]) == False

                if spacelessCheck(previousText[-1:]) and spacelessCheck(elementText[0:1]):
                    isSpace = gap >= size * 0.25 and icu.Char.isalpha(previousText[-1:]) and icu.Char.isalpha(elementText[0:1])

                current["text"] = f"{previousText} {elementText}" if isSpace else f"{previousText}{elementText}"

                if current["isVertical"]:
                    current["y1"] = element["y1"]
                    current["x0"] = min(current["x0"], element["x0"])
                    current["x1"] = max(current["x1"], element["x1"])
                else:
                    current["x1"] = element["x1"]
                    current["y0"] = min(current["y0"], element["y0"])
                    current["y1"] = max(current["y1"], element["y1"])
            else:
                resultList.append(current)

                for b in range(len(pendingList)):
                    resultList.append(pendingList[b])

                pendingList = []
                current = element

    if current is not None:
        resultList.append(current)

    for a in range(len(pendingList)):
        resultList.append(pendingList[a])

    return resultList

def gapOccupiedCheck(current, elementList, element, size):
    nameFlow = "y" if current["isVertical"] else "x"
    nameCross = "x" if current["isVertical"] else "y"

    for a in range(len(elementList)):
        other = elementList[a]

        if other["type"] != "text" or other is element or other["isVertical"] != current["isVertical"]:
            continue

        if abs(other[f"{nameCross}0"] - element[f"{nameCross}0"]) > size * 0.6:
            continue

        center = (other[f"{nameFlow}0"] + other[f"{nameFlow}1"]) / 2

        if center > current[f"{nameFlow}1"] and center < element[f"{nameFlow}0"]:
            return True

    return False

class Pdf:
    def _byteText(self, byteList):
        return byteList.decode("latin-1")

    def _decryptBuild(self, password):
        matchEncrypt = re.search(r"/Encrypt\s+(\d+)\s+(\d+)\s+R", self.text)

        if matchEncrypt is None:
            return ""

        entryObject = self._encryptEntry(int(matchEncrypt.group(1)))

        if entryObject is None:
            return self.messageEncryption

        filterNode = entryObject.get("Filter")

        if filterNode is None or filterNode["kind"] != "name" or filterNode["value"] != "Standard":
            return self.messageEncryption

        version = int(self._numberValue(entryObject.get("V")))
        revision = int(self._numberValue(entryObject.get("R")))

        if version not in self.versionEncryptList:
            return self.messageEncryption

        ownerByteList = self._stringByte(entryObject.get("O"))
        userByteList = self._stringByte(entryObject.get("U"))

        methodObject = self._cryptMethod(entryObject, version)

        if version == 5:
            keyList = self._keyAes256(password, revision, userByteList, self._stringByte(entryObject.get("UE")), ownerByteList, self._stringByte(entryObject.get("OE")))
        else:
            keyList = self._keyStandard(password, revision, entryObject, ownerByteList, userByteList)

        if keyList is None:
            return self.messagePasswordWrong if len(password) > 0 else self.messagePasswordRequired

        self.decryptObject = {
            "keyList": keyList,
            "isAes256": version == 5,
            "methodStream": methodObject["stream"],
            "methodString": methodObject["string"]
        }

        return ""

    def _encryptEntry(self, number):
        match = re.search(rf"(?<!\d)(?<!\d\s){number}\s+\d+\s+obj\b", self.text)

        if match is None:
            return None

        self.position = match.end()

        value = self._parseValue()

        return value.get("entryObject")

    def _stringByte(self, node):
        if node is None or (node["kind"] != "string" and node["kind"] != "hexString"):
            return b""

        return node["value"].encode("latin-1")

    def _cryptMethod(self, entryObject, version):
        if version < 4:
            return {"stream": "RC4", "string": "RC4"}

        filterObject = {}

        cryptNode = self._resolve(entryObject.get("CF"))

        if cryptNode is not None and cryptNode.get("entryObject") is not None:
            for name in cryptNode["entryObject"]:
                methodNode = self._resolve(cryptNode["entryObject"][name])

                if methodNode is not None and methodNode.get("entryObject") is not None:
                    codeNode = methodNode["entryObject"].get("CFM")

                    if codeNode is not None and codeNode["kind"] == "name":
                        filterObject[name] = "AES" if codeNode["value"] == "AESV2" or codeNode["value"] == "AESV3" else "RC4"

        return {
            "stream": self._cryptName(entryObject.get("StmF"), filterObject),
            "string": self._cryptName(entryObject.get("StrF"), filterObject)
        }

    def _cryptName(self, node, filterObject):
        if node is None or node["kind"] != "name" or node["value"] == "Identity":
            return "Identity"

        return filterObject[node["value"]] if node["value"] in filterObject else "Identity"

    def _keyStandard(self, password, revision, entryObject, ownerByteList, userByteList):
        idByteList = self._idByte()

        permission = int(self._numberValue(entryObject.get("P")))

        countByte = 5 if revision == 2 else int(self._numberValue(entryObject.get("Length")) / 8)

        if countByte <= 0:
            countByte = 5

        isMetadata = True

        metadataNode = entryObject.get("EncryptMetadata")

        if metadataNode is not None and metadataNode["kind"] == "boolean":
            isMetadata = metadataNode["value"]

        keyList = self._keyCompute(password.encode("latin-1", "ignore"), revision, countByte, ownerByteList, permission, idByteList, isMetadata)

        if self._userCheck(keyList, revision, userByteList, idByteList):
            return keyList

        passwordUser = self._passwordOwner(password.encode("latin-1", "ignore"), revision, countByte, ownerByteList)

        keyList = self._keyCompute(passwordUser, revision, countByte, ownerByteList, permission, idByteList, isMetadata)

        if self._userCheck(keyList, revision, userByteList, idByteList):
            return keyList

        return None

    def _idByte(self):
        match = re.search(r"/ID\s*\[", self.text)

        if match is None:
            return b""

        self.position = match.end() - 1

        value = self._parseValue()

        if value["kind"] != "array" or value.get("itemList") is None or len(value["itemList"]) == 0:
            return b""

        return self._stringByte(value["itemList"][0])

    def _keyCompute(self, passwordByteList, revision, countByte, ownerByteList, permission, idByteList, isMetadata):
        digest = hashlib.md5()

        digest.update((passwordByteList + self.paddingByteList)[0:32])
        digest.update(ownerByteList[0:32])
        digest.update((permission & 0xffffffff).to_bytes(4, "little"))
        digest.update(idByteList)

        if revision >= 4 and isMetadata == False:
            digest.update(b"\xff\xff\xff\xff")

        keyList = digest.digest()

        if revision >= 3:
            for a in range(50):
                keyList = hashlib.md5(keyList[0:countByte]).digest()

        return keyList[0:countByte]

    def _userCheck(self, keyList, revision, userByteList, idByteList):
        if revision == 2:
            return self._rc4(keyList, self.paddingByteList) == userByteList[0:32]

        value = self._rc4(keyList, hashlib.md5(self.paddingByteList + idByteList).digest())

        for a in range(1, 20):
            value = self._rc4(self._keyXor(keyList, a), value)

        return value == userByteList[0:16]

    def _keyXor(self, keyList, value):
        resultList = bytearray()

        for a in range(len(keyList)):
            resultList.append(keyList[a] ^ value)

        return bytes(resultList)

    def _passwordOwner(self, passwordByteList, revision, countByte, ownerByteList):
        keyList = hashlib.md5((passwordByteList + self.paddingByteList)[0:32]).digest()

        if revision >= 3:
            for a in range(50):
                keyList = hashlib.md5(keyList).digest()

        keyList = keyList[0:countByte]

        if revision == 2:
            return self._rc4(keyList, ownerByteList)

        value = ownerByteList

        for a in range(19, -1, -1):
            value = self._rc4(self._keyXor(keyList, a), value)

        return value

    def _keyAes256(self, password, revision, userByteList, userKeyByteList, ownerByteList, ownerKeyByteList):
        passwordByteList = password.encode("utf-8")

        if len(userByteList) >= 48 and self._hashAes256(revision, passwordByteList, userByteList[32:40], b"") == userByteList[0:32]:
            return self._aesDecryptNoPad(self._hashAes256(revision, passwordByteList, userByteList[40:48], b""), userKeyByteList)

        if len(ownerByteList) >= 48 and self._hashAes256(revision, passwordByteList, ownerByteList[32:40], userByteList[0:48]) == ownerByteList[0:32]:
            return self._aesDecryptNoPad(self._hashAes256(revision, passwordByteList, ownerByteList[40:48], userByteList[0:48]), ownerKeyByteList)

        return None

    def _hashAes256(self, revision, passwordByteList, saltByteList, userByteList):
        digest = hashlib.sha256(passwordByteList + saltByteList + userByteList).digest()

        if revision == 5:
            return digest

        count = 0

        while True:
            dataList = (passwordByteList + digest + userByteList) * 64

            encryptedList = self._aesEncryptNoPad(digest[0:16], digest[16:32], dataList)

            total = 0

            for a in range(16):
                total += encryptedList[a]

            index = total % 3

            if index == 0:
                digest = hashlib.sha256(encryptedList).digest()
            elif index == 1:
                digest = hashlib.sha384(encryptedList).digest()
            else:
                digest = hashlib.sha512(encryptedList).digest()

            count += 1

            if count >= 64 and encryptedList[len(encryptedList) - 1] <= count - 32:
                break

        return digest[0:32]

    def _aesEncryptNoPad(self, keyList, vectorList, byteList):
        encryptor = Cipher(algorithms.AES(keyList), modes.CBC(vectorList)).encryptor()

        return encryptor.update(byteList) + encryptor.finalize()

    def _aesDecryptNoPad(self, keyList, byteList):
        countBlock = int(len(byteList) / 16) * 16

        if countBlock == 0:
            return b""

        decryptor = Cipher(algorithms.AES(keyList), modes.CBC(bytes(16))).decryptor()

        return decryptor.update(byteList[0:countBlock]) + decryptor.finalize()

    def _aesDecrypt(self, keyList, byteList):
        countBlock = int((len(byteList) - 16) / 16) * 16

        if len(byteList) <= 16 or countBlock == 0:
            return b""

        decryptor = Cipher(algorithms.AES(keyList), modes.CBC(byteList[0:16])).decryptor()

        resultList = decryptor.update(byteList[16:16 + countBlock]) + decryptor.finalize()

        countPadding = resultList[len(resultList) - 1]

        if countPadding >= 1 and countPadding <= 16 and countPadding <= len(resultList):
            return resultList[0:len(resultList) - countPadding]

        return resultList

    def _rc4(self, keyList, byteList):
        stateList = list(range(256))

        indexState = 0

        for a in range(256):
            indexState = (indexState + stateList[a] + keyList[a % len(keyList)]) % 256

            stateList[a], stateList[indexState] = stateList[indexState], stateList[a]

        resultList = bytearray()

        indexA = 0
        indexB = 0

        for a in range(len(byteList)):
            indexA = (indexA + 1) % 256
            indexB = (indexB + stateList[indexA]) % 256

            stateList[indexA], stateList[indexB] = stateList[indexB], stateList[indexA]

            resultList.append(byteList[a] ^ stateList[(stateList[indexA] + stateList[indexB]) % 256])

        return bytes(resultList)

    def _decryptByte(self, byteList, isStream):
        if self.decryptObject is None or self.isDecryptActive == False:
            return byteList

        method = self.decryptObject["methodStream"] if isStream else self.decryptObject["methodString"]

        if method == "Identity":
            return byteList

        keyList = self._keyObject()

        if method == "AES":
            return self._aesDecrypt(keyList, byteList)

        return self._rc4(keyList, byteList)

    def _keyObject(self):
        keyList = self.decryptObject["keyList"]

        if self.decryptObject["isAes256"]:
            return keyList

        digest = hashlib.md5()

        digest.update(keyList)
        digest.update(bytes([self.numberObject & 0xff, (self.numberObject >> 8) & 0xff, (self.numberObject >> 16) & 0xff]))
        digest.update(bytes([self.generationObject & 0xff, (self.generationObject >> 8) & 0xff]))

        if self.decryptObject["methodStream"] == "AES" or self.decryptObject["methodString"] == "AES":
            digest.update(b"sAlT")

        return digest.digest()[0:min(len(keyList) + 5, 16)]

    def _parseIndirect(self):
        resultList = []

        matchList = list(re.finditer(r"(\d+)\s+(\d+)\s+obj\b", self.text))

        for a in range(len(matchList)):
            self.position = matchList[a].end()

            self.numberObject = int(matchList[a].group(1))
            self.generationObject = int(matchList[a].group(2))

            self.isDecryptActive = True

            value = self._parseValue()

            self.isDecryptActive = False

            category = value["kind"]

            if (value["kind"] == "dictionary" or value["kind"] == "stream") and value.get("category") is not None:
                category = value["category"]

            resultList.append({
                "number": int(matchList[a].group(1)),
                "generation": int(matchList[a].group(2)),
                "category": category,
                "value": value
            })

        expandedList = []

        for a in range(len(resultList)):
            nestedList = self._streamIndirectExpand(resultList[a])

            for b in range(len(nestedList)):
                expandedList.append(nestedList[b])

        for a in range(len(expandedList)):
            resultList.append(expandedList[a])

        return resultList

    def _parseValue(self):
        self._skipWhitespace()

        code = self.byteList[self.position] if self.position < len(self.byteList) else 0

        if code == 47:
            result = self._parseName()
        elif code == 40:
            result = self._parseLiteralString()
        elif code == 60 and self.position + 1 < len(self.byteList) and self.byteList[self.position + 1] == 60:
            result = self._parseDictionaryOrStream()
        elif code == 60:
            result = self._parseHexString()
        elif code == 91:
            result = self._parseArray()
        elif self._digitCheck(code) or code == 43 or code == 45 or code == 46:
            result = self._parseNumberOrReference()
        elif self.text[self.position:self.position + 4] == "true":
            self.position += 4
            result = {"kind": "boolean", "value": True}
        elif self.text[self.position:self.position + 5] == "false":
            self.position += 5
            result = {"kind": "boolean", "value": False}
        elif self.text[self.position:self.position + 4] == "null":
            self.position += 4
            result = {"kind": "null"}
        else:
            operator = ""

            while (
                self.position < len(self.byteList)
                and self._whitespaceCheck(self.byteList[self.position]) == False
                and self._delimiterCheck(self.byteList[self.position]) == False
            ):
                operator += chr(self.byteList[self.position])
                self.position += 1

            result = {"kind": "operator", "value": operator}

        return result

    def _skipWhitespace(self):
        byteList = self.byteList
        length = len(byteList)

        isRunning = True

        while isRunning:
            if self.position >= length:
                isRunning = False
            else:
                code = byteList[self.position]

                if code in self.whitespaceSet:
                    self.position += 1
                elif code == 37:
                    while self.position < length and byteList[self.position] != 10 and byteList[self.position] != 13:
                        self.position += 1
                else:
                    isRunning = False

    def _parseName(self):
        self.position += 1

        value = ""
        isRunning = True

        while isRunning:
            if self.position >= len(self.byteList):
                isRunning = False
            else:
                code = self.byteList[self.position]

                if self._whitespaceCheck(code) or self._delimiterCheck(code):
                    isRunning = False
                elif code == 35:
                    hexText = self.text[self.position + 1:self.position + 3]

                    if re.fullmatch(r"[0-9A-Fa-f]{2}", hexText) is not None:
                        value += chr(int(hexText, 16))

                    self.position += 3
                else:
                    value += chr(code)
                    self.position += 1

        return {"kind": "name", "value": value}

    def _whitespaceCheck(self, code):
        return code in self.whitespaceSet

    def _delimiterCheck(self, code):
        return code in self.delimiterSet

    def _parseLiteralString(self):
        self.position += 1

        value = ""
        depth = 1

        while depth > 0 and self.position < len(self.byteList):
            code = self.byteList[self.position]

            if code == 92:
                nextCode = self.byteList[self.position + 1] if self.position + 1 < len(self.byteList) else 0

                if nextCode == 110:
                    value += "\n"
                    self.position += 2
                elif nextCode == 114:
                    value += "\r"
                    self.position += 2
                elif nextCode == 116:
                    value += "\t"
                    self.position += 2
                elif nextCode >= 48 and nextCode <= 55:
                    octalText = ""
                    count = 0

                    self.position += 1

                    while count < 3 and self.position < len(self.byteList) and self.byteList[self.position] >= 48 and self.byteList[self.position] <= 55:
                        octalText += chr(self.byteList[self.position])
                        self.position += 1
                        count += 1

                    if len(octalText) > 0:
                        value += chr(int(octalText, 8) & 0xff)
                else:
                    value += chr(nextCode)
                    self.position += 2
            elif code == 40:
                depth += 1
                value += "("
                self.position += 1
            elif code == 41:
                depth -= 1

                if depth > 0:
                    value += ")"

                self.position += 1
            else:
                value += chr(code)
                self.position += 1

        return {"kind": "string", "value": self._byteText(self._decryptByte(value.encode("latin-1"), False))}

    def _parseDictionaryOrStream(self):
        self.position += 2

        entryObject = {}

        isRunning = True

        while isRunning:
            self._skipWhitespace()

            if self.position >= len(self.byteList):
                isRunning = False
            elif self.byteList[self.position] == 62 and self.position + 1 < len(self.byteList) and self.byteList[self.position + 1] == 62:
                self.position += 2
                isRunning = False
            elif self.byteList[self.position] == 47:
                nameNode = self._parseName()

                self._skipWhitespace()

                entryObject[nameNode["value"]] = self._parseValue()
            else:
                isRunning = False

        category = self._dictionaryCategory(entryObject)

        self._skipWhitespace()

        result = {"kind": "dictionary", "category": category, "entryObject": entryObject}

        if self.text[self.position:self.position + 6] == "stream":
            result = self._parseStream(entryObject, category)

        return result

    def _dictionaryCategory(self, entryObject):
        result = "dictionary"

        typeNode = entryObject.get("Type")

        if typeNode is not None and typeNode["kind"] == "name":
            result = typeNode["value"]

            subtypeNode = entryObject.get("Subtype")

            if subtypeNode is not None and subtypeNode["kind"] == "name":
                result = f"{typeNode['value']}:{subtypeNode['value']}"

        return result

    def _parseStream(self, entryObject, category):
        self.position += 6

        if self.position < len(self.byteList) and self.byteList[self.position] == 13:
            self.position += 1

        if self.position < len(self.byteList) and self.byteList[self.position] == 10:
            self.position += 1

        start = self.position
        endIndex = self.text.find("endstream", start)

        if endIndex < 0:
            endIndex = len(self.byteList)

        end = endIndex

        if end - 1 >= 0 and end - 1 < len(self.byteList) and self.byteList[end - 1] == 10:
            end -= 1

        if end - 1 >= 0 and end - 1 < len(self.byteList) and self.byteList[end - 1] == 13:
            end -= 1

        rawList = self.byteList[start:end]

        if category != "XRef":
            rawList = self._decryptByte(bytes(rawList), True)

        self.position = endIndex + 9

        filterList = self._filterExtract(entryObject)
        isImage = "Image" in category or "DCTDecode" in filterList or "JPXDecode" in filterList

        result = {
            "kind": "stream",
            "category": category,
            "entryObject": entryObject,
            "filterList": filterList,
            "rawByteLength": len(rawList)
        }

        if isImage:
            result["isImage"] = True
        else:
            decodedList = self._decodeStream(rawList, filterList, entryObject)

            result["decodedByteLength"] = len(decodedList)
            result["content"] = self._byteText(decodedList)

        return result

    def _filterExtract(self, entryObject):
        resultList = []

        filterNode = entryObject.get("Filter")

        if filterNode is not None:
            if filterNode["kind"] == "name":
                resultList.append(filterNode["value"])
            elif filterNode["kind"] == "array" and filterNode.get("itemList") is not None:
                for a in range(len(filterNode["itemList"])):
                    item = filterNode["itemList"][a]

                    if item["kind"] == "name":
                        resultList.append(item["value"])

        return resultList

    def _decodeStream(self, rawList, filterList, entryObject):
        result = rawList

        for a in range(len(filterList)):
            if filterList[a] == "ASCII85Decode" or filterList[a] == "A85":
                result = self._ascii85Decode(result)
            elif filterList[a] == "ASCIIHexDecode" or filterList[a] == "AHx":
                result = self._asciiHexDecode(result)
            elif filterList[a] == "RunLengthDecode" or filterList[a] == "RL":
                result = self._runLengthDecode(result)
            elif filterList[a] == "LZWDecode" or filterList[a] == "LZW":
                result = self._lzwDecode(result, self._earlyChangeValue(entryObject))
                result = self._applyPredictor(result, entryObject)
            elif filterList[a] == "FlateDecode" or filterList[a] == "Fl":
                result = self._inflate(result)
                result = self._applyPredictor(result, entryObject)

        return result

    def _ascii85Decode(self, byteList):
        result = bytes(byteList).strip()

        if result.startswith(b"<~"):
            result = result[2:]

        indexEnd = result.find(b"~>")

        if indexEnd >= 0:
            result = result[:indexEnd]

        return base64.a85decode(result)

    def _asciiHexDecode(self, byteList):
        text = bytes(byteList).decode("latin-1")

        indexEnd = text.find(">")

        if indexEnd >= 0:
            text = text[:indexEnd]

        result = ""

        for a in range(len(text)):
            if whitespaceCheck(text[a]) == False:
                result += text[a]

        if len(result) % 2 == 1:
            result += "0"

        return bytes.fromhex(result)

    def _runLengthDecode(self, byteList):
        result = bytearray()
        position = 0

        while position < len(byteList):
            length = byteList[position]
            position += 1

            if length == 128:
                break

            if length < 128:
                result += byteList[position:position + length + 1]
                position += length + 1

                continue

            result += bytes([byteList[position]]) * (257 - length)
            position += 1

        return bytes(result)

    def _earlyChangeValue(self, entryObject):
        result = 1

        parmsNode = entryObject.get("DecodeParms")

        if parmsNode is not None and parmsNode["kind"] == "dictionary" and parmsNode.get("entryObject") is not None:
            earlyNode = parmsNode["entryObject"].get("EarlyChange")

            if earlyNode is not None and earlyNode["kind"] == "number":
                result = int(earlyNode["value"])

        return result

    def _lzwDecode(self, byteList, earlyChange):
        dictionaryList = [bytes([a]) for a in range(256)] + [b"", b""]

        result = bytearray()
        previousList = None
        codeWidth = 9
        buffer = 0
        bufferLength = 0

        for a in range(len(byteList)):
            buffer = (buffer << 8) | byteList[a]
            bufferLength += 8

            while bufferLength >= codeWidth:
                code = (buffer >> (bufferLength - codeWidth)) & ((1 << codeWidth) - 1)
                bufferLength -= codeWidth

                if code == 257:
                    return bytes(result)

                if code == 256:
                    dictionaryList = dictionaryList[0:258]
                    previousList = None
                    codeWidth = 9

                    continue

                if previousList is None:
                    entryList = dictionaryList[code]
                elif code < len(dictionaryList):
                    entryList = dictionaryList[code]

                    dictionaryList.append(previousList + entryList[0:1])
                else:
                    entryList = previousList + previousList[0:1]

                    dictionaryList.append(entryList)

                result += entryList
                previousList = entryList

                if len(dictionaryList) + earlyChange >= (1 << codeWidth) and codeWidth < 12:
                    codeWidth += 1

        return bytes(result)

    def _inflate(self, byteList):
        isZlibHeader = False

        if len(byteList) >= 2:
            byte0 = byteList[0]
            byte1 = byteList[1]

            isZlibHeader = (byte0 & 0x0f) == 8 and ((byte0 << 8) | byte1) % 31 == 0

        decompressor = zlib.decompressobj() if isZlibHeader else zlib.decompressobj(-15)

        return decompressor.decompress(bytes(byteList))

    def _applyPredictor(self, byteList, entryObject):
        result = byteList

        parmsNode = entryObject.get("DecodeParms")

        if parmsNode is not None and parmsNode["kind"] == "dictionary" and parmsNode.get("entryObject") is not None:
            predictorNode = parmsNode["entryObject"].get("Predictor")
            columnsNode = parmsNode["entryObject"].get("Columns")

            if predictorNode is not None and predictorNode["kind"] == "number" and predictorNode["value"] >= 10:
                columns = int(columnsNode["value"]) if columnsNode is not None and columnsNode["kind"] == "number" else 1

                result = self._applyPngPredictor(columns, byteList)

        return result

    def _applyPngPredictor(self, columns, byteList):
        rowLength = columns + 1
        rowCount = len(byteList) // rowLength

        resultList = bytearray(rowCount * columns)

        previousList = bytearray(columns)

        for row in range(rowCount):
            filterType = byteList[row * rowLength]
            currentList = bytearray(columns)

            for a in range(columns):
                value = byteList[row * rowLength + 1 + a]
                left = currentList[a - 1] if a >= 1 else 0
                up = previousList[a]
                upLeft = previousList[a - 1] if a >= 1 else 0

                restored = value

                if filterType == 1:
                    restored = value + left
                elif filterType == 2:
                    restored = value + up
                elif filterType == 3:
                    restored = value + (left + up) // 2
                elif filterType == 4:
                    paeth = left + up - upLeft
                    paethLeft = abs(paeth - left)
                    paethUp = abs(paeth - up)
                    paethUpLeft = abs(paeth - upLeft)

                    predictor = upLeft

                    if paethLeft <= paethUp and paethLeft <= paethUpLeft:
                        predictor = left
                    elif paethUp <= paethUpLeft:
                        predictor = up

                    restored = value + predictor

                currentList[a] = restored & 0xff
                resultList[row * columns + a] = currentList[a]

            previousList = currentList

        return bytes(resultList)

    def _parseHexString(self):
        self.position += 1

        byteList = self.byteList
        length = len(byteList)

        startPosition = self.position

        while self.position < length and byteList[self.position] != 62:
            self.position += 1

        hexText = re.sub(r"[^0-9A-Fa-f]", "", self.text[startPosition:self.position])

        self.position += 1

        if len(hexText) % 2 == 1:
            hexText += "0"

        value = self._byteText(self._decryptByte(bytes.fromhex(hexText), False))

        return {"kind": "hexString", "value": value}

    def _parseArray(self):
        self.position += 1

        itemList = []

        isRunning = True

        while isRunning:
            self._skipWhitespace()

            if self.position >= len(self.byteList) or self.byteList[self.position] == 93:
                self.position += 1
                isRunning = False
            else:
                itemList.append(self._parseValue())

        return {"kind": "array", "itemList": itemList}

    def _digitCheck(self, code):
        return code >= 48 and code <= 57

    def _positionAdvance(self, codeSet):
        byteList = self.byteList
        length = len(byteList)
        position = self.position

        while position < length and byteList[position] in codeSet:
            position += 1

        self.position = position

    def _parseNumberOrReference(self):
        savedPosition = self.position

        self._positionAdvance(self.numberSet)

        numberText = self.text[savedPosition:self.position]

        firstNumber = self._floatParse(numberText)

        result = {"kind": "number", "value": firstNumber}

        if "." not in numberText:
            afterFirst = self.position

            self._skipWhitespace()

            secondPosition = self.position

            self._positionAdvance(self.digitSet)

            secondText = self.text[secondPosition:self.position]

            if len(secondText) > 0:
                self._skipWhitespace()

                if self.position < len(self.byteList) and self.byteList[self.position] == 82:
                    self.position += 1
                    result = {"kind": "reference", "number": int(firstNumber), "generation": int(secondText)}
                else:
                    self.position = afterFirst
            else:
                self.position = afterFirst

        if result["kind"] == "number":
            self.position = savedPosition + len(numberText)

        return result

    def _floatParse(self, text):
        result = 0.0

        match = re.match(r"[+-]?(\d+\.?\d*|\.\d+)", text)

        if match is not None:
            result = float(match.group(0))

        return result

    def _streamIndirectExpand(self, indirect):
        resultList = []

        streamNode = indirect["value"]

        if streamNode["kind"] == "stream" and streamNode.get("category") == "ObjStm" and streamNode.get("content") is not None and streamNode.get("entryObject") is not None:
            countNode = streamNode["entryObject"].get("N")
            firstNode = streamNode["entryObject"].get("First")

            if countNode is not None and countNode["kind"] == "number" and firstNode is not None and firstNode["kind"] == "number":
                count = int(countNode["value"])
                first = int(firstNode["value"])

                savedByteList = self.byteList
                savedText = self.text
                savedPosition = self.position

                self.text = streamNode["content"]
                self.byteList = self._textByte(streamNode["content"])

                headerList = []

                self.position = 0

                for a in range(count):
                    self._skipWhitespace()
                    numberNode = self._parseValue()
                    self._skipWhitespace()
                    offsetNode = self._parseValue()

                    if numberNode["kind"] == "number" and offsetNode["kind"] == "number":
                        headerList.append({"number": int(numberNode["value"]), "offset": int(offsetNode["value"])})

                for a in range(len(headerList)):
                    self.position = first + headerList[a]["offset"]

                    value = self._parseValue()

                    category = value["kind"]

                    if (value["kind"] == "dictionary" or value["kind"] == "stream") and value.get("category") is not None:
                        category = value["category"]

                    resultList.append({"number": headerList[a]["number"], "generation": 0, "category": category, "value": value})

                self.byteList = savedByteList
                self.text = savedText
                self.position = savedPosition

        return resultList

    def _textByte(self, text):
        return text.encode("latin-1", errors="replace")

    def _buildPage(self):
        resultList = []

        trailerIndex = self.text.rfind("trailer")

        rootNode = None

        if trailerIndex >= 0:
            self.position = trailerIndex + 7
            self._skipWhitespace()

            trailer = self._parseValue()

            if trailer.get("entryObject") is not None:
                rootNode = trailer["entryObject"].get("Root")

        if rootNode is None:
            indirectList = list(self.indirectObject.values())

            for a in range(len(indirectList)):
                if indirectList[a]["category"] == "Catalog":
                    rootNode = indirectList[a]["value"]

        catalog = self._resolve(rootNode)
        pageRawList = []

        if catalog is not None and catalog.get("entryObject") is not None:
            self._collectPage(catalog["entryObject"].get("Pages"), {"resourceObject": {}, "mediaBoxList": [0, 0, 595, 842], "cropBoxList": None, "rotate": 0}, pageRawList)

        for a in range(len(pageRawList)):
            pageRaw = pageRawList[a]

            self.ctmList = [1, 0, 0, 1, 0, 0]
            self.textMatrixList = [1, 0, 0, 1, 0, 0]
            self.lineMatrixList = [1, 0, 0, 1, 0, 0]
            self.graphicsStateList = []
            self.fontSize = 0
            self.charSpacing = 0
            self.wordSpacing = 0
            self.horizontalScale = 1
            self.leading = 0
            self.textRender = 0
            self.textRise = 0
            self.fillColor = "#000000"
            self.strokeColor = "#000000"
            self.currentFont = None
            self._pathReset()

            boxList = pageRaw["boxList"]

            width = boxList[2] - boxList[0]
            height = boxList[3] - boxList[1]

            self.pageHeight = boxList[3]
            self.elementList = []

            content = self._pageContent(pageRaw["entryObject"])

            self._interpretContent(content, pageRaw["resourceObject"])

            elementList = self._elementTransform(self.elementList, boxList[0], pageRaw["rotate"], width, height)

            if pageRaw["rotate"] == 90 or pageRaw["rotate"] == 270:
                width, height = height, width

            resultList.append({"number": a + 1, "width": width, "height": height, "rotate": pageRaw["rotate"], "elementList": elementList})

        return resultList

    def _elementTransform(self, elementList, offsetX, rotate, width, height):
        for a in range(len(elementList)):
            x0 = elementList[a]["x0"] - offsetX
            x1 = elementList[a]["x1"] - offsetX
            y0 = elementList[a]["y0"]
            y1 = elementList[a]["y1"]

            if rotate == 90:
                pointList = [[height - y0, x0], [height - y1, x1]]
            elif rotate == 180:
                pointList = [[width - x0, height - y0], [width - x1, height - y1]]
            elif rotate == 270:
                pointList = [[y0, width - x0], [y1, width - x1]]
            else:
                pointList = [[x0, y0], [x1, y1]]

            elementList[a]["x0"] = min(pointList[0][0], pointList[1][0])
            elementList[a]["y0"] = min(pointList[0][1], pointList[1][1])
            elementList[a]["x1"] = max(pointList[0][0], pointList[1][0])
            elementList[a]["y1"] = max(pointList[0][1], pointList[1][1])

        return elementList

    def _resolve(self, node):
        result = node

        while result is not None and result["kind"] == "reference":
            found = self.indirectObject.get(result["number"])

            result = found["value"] if found is not None else None

        return result

    def _collectPage(self, node, parentObject, resultList):
        resolved = self._resolve(node)

        if resolved is not None and resolved.get("entryObject") is not None:
            entryObject = resolved["entryObject"]

            inheritObject = {
                "resourceObject": parentObject["resourceObject"],
                "mediaBoxList": parentObject["mediaBoxList"],
                "cropBoxList": parentObject["cropBoxList"],
                "rotate": parentObject["rotate"]
            }

            resourceNode = self._resolve(entryObject.get("Resources"))

            if resourceNode is not None and resourceNode.get("entryObject") is not None:
                inheritObject["resourceObject"] = resourceNode["entryObject"]

            mediaBoxList = self._boxValue(entryObject, "MediaBox")

            if mediaBoxList is not None:
                inheritObject["mediaBoxList"] = mediaBoxList

            cropBoxList = self._boxValue(entryObject, "CropBox")

            if cropBoxList is not None:
                inheritObject["cropBoxList"] = cropBoxList

            rotateNode = self._resolve(entryObject.get("Rotate"))

            if rotateNode is not None and rotateNode["kind"] == "number":
                inheritObject["rotate"] = int(rotateNode["value"])

            typeNode = self._resolve(entryObject.get("Type"))
            type = typeNode["value"] if typeNode is not None and typeNode["kind"] == "name" else ""

            kidsNode = self._resolve(entryObject.get("Kids"))

            if type == "Page" or (type != "Pages" and kidsNode is None):
                resultList.append({
                    "entryObject": entryObject,
                    "resourceObject": inheritObject["resourceObject"],
                    "boxList": self._viewBox(inheritObject["mediaBoxList"], inheritObject["cropBoxList"]),
                    "rotate": inheritObject["rotate"] % 360
                })
            elif kidsNode is not None and kidsNode["kind"] == "array" and kidsNode.get("itemList") is not None:
                for a in range(len(kidsNode["itemList"])):
                    self._collectPage(kidsNode["itemList"][a], inheritObject, resultList)

    def _boxValue(self, entryObject, key):
        boxNode = self._resolve(entryObject.get(key))

        if boxNode is None or boxNode["kind"] != "array" or boxNode.get("itemList") is None:
            return None

        itemList = boxNode["itemList"]

        valueList = [
            self._numberValue(itemList[0] if len(itemList) > 0 else None),
            self._numberValue(itemList[1] if len(itemList) > 1 else None),
            self._numberValue(itemList[2] if len(itemList) > 2 else None),
            self._numberValue(itemList[3] if len(itemList) > 3 else None)
        ]

        return [min(valueList[0], valueList[2]), min(valueList[1], valueList[3]), max(valueList[0], valueList[2]), max(valueList[1], valueList[3])]

    def _viewBox(self, mediaBoxList, cropBoxList):
        if cropBoxList is None:
            return mediaBoxList

        resultList = [
            max(mediaBoxList[0], cropBoxList[0]),
            max(mediaBoxList[1], cropBoxList[1]),
            min(mediaBoxList[2], cropBoxList[2]),
            min(mediaBoxList[3], cropBoxList[3])
        ]

        if resultList[2] <= resultList[0] or resultList[3] <= resultList[1]:
            return mediaBoxList

        return resultList

    def _numberValue(self, node):
        result = 0

        resolved = self._resolve(node)

        if resolved is not None and resolved["kind"] == "number":
            result = resolved["value"]

        return result

    def _pathReset(self):
        self.isPathEmpty = True
        self.isPathRectangle = False

    def _pageContent(self, entryObject):
        result = ""

        contentNode = self._resolve(entryObject.get("Contents"))

        if contentNode is not None:
            if contentNode["kind"] == "stream" and contentNode.get("content") is not None:
                result = contentNode["content"]
            elif contentNode["kind"] == "array" and contentNode.get("itemList") is not None:
                for a in range(len(contentNode["itemList"])):
                    part = self._resolve(contentNode["itemList"][a])

                    if part is not None and part["kind"] == "stream" and part.get("content") is not None:
                        result += f"{part['content']}\n"

        return result

    def _interpretContent(self, content, resourceObject):
        fontObject = self._resourceFont(resourceObject)
        externalObject = self._resourceExternal(resourceObject)
        stateObject = self._resourceState(resourceObject)

        self.byteList = self._textByte(content)
        self.text = content
        self.position = 0

        stackList = []

        while self.position < len(self.byteList):
            self._skipWhitespace()

            if self.position >= len(self.byteList):
                break

            node = self._parseValue()

            if node["kind"] == "operator":
                if len(node["value"]) > 0:
                    self._handleOperator(node["value"], stackList, stateObject, fontObject, externalObject)
                else:
                    self.position += 1

                stackList = []
            else:
                stackList.append(node)

    def _resourceFont(self, resourceObject):
        resultObject = {}

        fontNode = self._resolve(resourceObject.get("Font"))

        if fontNode is not None and fontNode["kind"] == "dictionary" and fontNode.get("entryObject") is not None:
            nameList = list(fontNode["entryObject"].keys())

            for a in range(len(nameList)):
                resolved = self._resolve(fontNode["entryObject"][nameList[a]])

                if resolved is not None:
                    resultObject[nameList[a]] = self._buildFont(resolved)

        return resultObject

    def _buildFont(self, fontNode):
        entryObject = fontNode["entryObject"] if fontNode.get("entryObject") is not None else {}

        baseFontNode = self._resolve(entryObject.get("BaseFont"))
        baseFont = baseFontNode["value"] if baseFontNode is not None and baseFontNode["kind"] == "name" else ""

        subtypeNode = self._resolve(entryObject.get("Subtype"))
        subtype = subtypeNode["value"] if subtypeNode is not None and subtypeNode["kind"] == "name" else ""

        encodingNode = self._resolve(entryObject.get("Encoding"))
        encoding = encodingNode["value"] if encodingNode is not None and encodingNode["kind"] == "name" else ""

        codecName = self._codecGet(encoding) if subtype == "Type0" else ""

        byteLength = 2 if subtype == "Type0" else 1

        result = {
            "baseFont": baseFont,
            "isVertical": self._verticalCheck(encoding, encodingNode),
            "verticalFraction": 1.0,
            "verticalObject": {},
            "byteLength": byteLength,
            "firstChar": 0,
            "widthList": [],
            "widthScale": 0.001,
            "widthObject": {},
            "defaultWidthFraction": 0.5,
            "codecName": codecName,
            "isUnicodeCode": codecName == "utf-16-be",
            "encodingObject": self._buildEncoding(encodingNode) if subtype != "Type0" else {},
            "toUnicodeObject": {}
        }

        toUnicodeNode = self._resolve(entryObject.get("ToUnicode"))

        if toUnicodeNode is not None and toUnicodeNode["kind"] == "stream" and toUnicodeNode.get("content") is not None:
            result["toUnicodeObject"] = self._buildToUnicode(toUnicodeNode["content"])

        if subtype == "Type0":
            descendantNode = self._resolve(entryObject.get("DescendantFonts"))

            if descendantNode is not None and descendantNode["kind"] == "array" and descendantNode.get("itemList") is not None:
                cidFontNode = self._resolve(descendantNode["itemList"][0] if len(descendantNode["itemList"]) > 0 else None)

                if cidFontNode is not None and cidFontNode.get("entryObject") is not None:
                    defaultWidthNode = self._resolve(cidFontNode["entryObject"].get("DW"))

                    result["defaultWidthFraction"] = defaultWidthNode["value"] / 1000 if defaultWidthNode is not None and defaultWidthNode["kind"] == "number" else 1
                    result["verticalFraction"] = self._verticalFraction(cidFontNode["entryObject"])
                    result["verticalObject"] = self._cidWidthVertical(cidFontNode["entryObject"])
                    result["widthObject"] = self._cidWidth(cidFontNode["entryObject"])
        else:
            firstCharNode = self._resolve(entryObject.get("FirstChar"))

            if firstCharNode is not None and firstCharNode["kind"] == "number":
                result["firstChar"] = int(firstCharNode["value"])

            widthsNode = self._resolve(entryObject.get("Widths"))

            if widthsNode is not None and widthsNode["kind"] == "array" and widthsNode.get("itemList") is not None:
                for a in range(len(widthsNode["itemList"])):
                    result["widthList"].append(self._numberValue(widthsNode["itemList"][a]))

            if subtype == "Type3":
                matrixNode = self._resolve(entryObject.get("FontMatrix"))

                if matrixNode is not None and matrixNode["kind"] == "array" and matrixNode.get("itemList") is not None:
                    result["widthScale"] = self._numberValue(matrixNode["itemList"][0] if len(matrixNode["itemList"]) > 0 else None)

        result["isCidResolved"] = subtype != "Type0" or encoding[0:8] == "Identity"

        result["isWidthEstimated"] = result["isCidResolved"] == False or (len(result["widthList"]) == 0 and len(result["widthObject"]) == 0)

        return result

    def _verticalCheck(self, encoding, encodingNode):
        if encoding[-2:] == "-V":
            return True

        streamNode = self._resolve(encodingNode)

        if streamNode is None or streamNode["kind"] != "stream" or streamNode.get("entryObject") is None:
            return False

        modeNode = self._resolve(streamNode["entryObject"].get("WMode"))

        return modeNode is not None and modeNode["kind"] == "number" and int(modeNode["value"]) == 1

    def _verticalFraction(self, entryObject):
        defaultNode = self._resolve(entryObject.get("DW2"))

        if defaultNode is None or defaultNode["kind"] != "array" or defaultNode.get("itemList") is None or len(defaultNode["itemList"]) < 2:
            return 1.0

        return abs(self._numberValue(defaultNode["itemList"][1])) / 1000

    def _codecGet(self, encoding):
        for a in range(len(self.codecList)):
            if self.codecList[a][0] in encoding:
                return self.codecList[a][1]

        return ""

    def _buildEncoding(self, encodingNode):
        resultObject = {}

        baseName = "/StandardEncoding"
        differenceNode = None

        if encodingNode is not None and encodingNode["kind"] == "name":
            baseName = encodingNode["value"]
        elif encodingNode is not None and encodingNode["kind"] == "dictionary" and encodingNode.get("entryObject") is not None:
            baseNode = self._resolve(encodingNode["entryObject"].get("BaseEncoding"))

            if baseNode is not None and baseNode["kind"] == "name":
                baseName = baseNode["value"]

            differenceNode = self._resolve(encodingNode["entryObject"].get("Differences"))

        codecName = "cp1252" if "WinAnsi" in baseName else "mac_roman" if "MacRoman" in baseName else "latin-1"

        for a in range(32, 256):
            character = bytes([a]).decode(codecName, errors="ignore")

            if len(character) > 0:
                resultObject[a] = character

        if differenceNode is not None and differenceNode["kind"] == "array" and differenceNode.get("itemList") is not None:
            code = 0

            for a in range(len(differenceNode["itemList"])):
                item = self._resolve(differenceNode["itemList"][a])

                if item is None:
                    continue

                if item["kind"] == "number":
                    code = int(item["value"])
                elif item["kind"] == "name":
                    character = self._glyphUnicode(item["value"])

                    if len(character) > 0:
                        resultObject[code] = character

                    code += 1

        return resultObject

    def _glyphUnicode(self, name):
        if len(name) == 1:
            return name

        return fontTools.agl.toUnicode(name)

    def _buildToUnicode(self, content):
        resultObject = {}

        charBlockList = list(re.finditer(r"beginbfchar([\s\S]*?)endbfchar", content))

        for a in range(len(charBlockList)):
            pairList = list(re.finditer(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", charBlockList[a].group(1)))

            for b in range(len(pairList)):
                resultObject[int(pairList[b].group(1), 16)] = self._utf16Hex(pairList[b].group(2))

        rangeBlockList = list(re.finditer(r"beginbfrange([\s\S]*?)endbfrange", content))

        for a in range(len(rangeBlockList)):
            lineList = list(re.finditer(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[\s\S]*?\]|<[0-9A-Fa-f]+>)", rangeBlockList[a].group(1)))

            for b in range(len(lineList)):
                low = int(lineList[b].group(1), 16)
                high = int(lineList[b].group(2), 16)
                destination = lineList[b].group(3)

                if destination[0:1] == "[":
                    itemList = list(re.finditer(r"<([0-9A-Fa-f]+)>", destination))
                    code = low

                    for c in range(len(itemList)):
                        if code <= high:
                            resultObject[code] = self._utf16Hex(itemList[c].group(1))
                            code += 1
                else:
                    base = int(destination.replace("<", "").replace(">", ""), 16)

                    for c in range(high - low + 1):
                        resultObject[low + c] = chr((base + c) & 0xffff)

        return resultObject

    def _utf16Hex(self, hexText):
        result = ""

        for a in range(0, len(hexText) - 3, 4):
            result += chr(int(hexText[a:a + 4], 16))

        return result

    def _cidWidthCollect(self, cidFontObject, nameKey, stepValue, countRange):
        resultObject = {}

        widthNode = self._resolve(cidFontObject.get(nameKey))

        if widthNode is None or widthNode["kind"] != "array" or widthNode.get("itemList") is None:
            return resultObject

        itemList = widthNode["itemList"]

        a = 0

        while a < len(itemList):
            first = self._numberValue(itemList[a])
            second = self._resolve(itemList[a + 1]) if a + 1 < len(itemList) else None

            if second is not None and second["kind"] == "array" and second.get("itemList") is not None:
                for b in range(0, len(second["itemList"]), stepValue):
                    resultObject[int(first) + int(b / stepValue)] = abs(self._numberValue(second["itemList"][b])) / 1000

                a += 2

                continue

            last = self._numberValue(itemList[a + 1]) if a + 1 < len(itemList) else 0
            width = abs(self._numberValue(itemList[a + 2])) / 1000 if a + 2 < len(itemList) else 0

            for cid in range(int(first), int(last) + 1):
                resultObject[cid] = width

            a += countRange

        return resultObject

    def _cidWidth(self, cidFontObject):
        return self._cidWidthCollect(cidFontObject, "W", 1, 3)

    def _cidWidthVertical(self, cidFontObject):
        return self._cidWidthCollect(cidFontObject, "W2", 3, 5)

    def _resourceExternal(self, resourceObject):
        resultObject = {}

        externalNode = self._resolve(resourceObject.get("XObject"))

        if externalNode is not None and externalNode["kind"] == "dictionary" and externalNode.get("entryObject") is not None:
            nameList = list(externalNode["entryObject"].keys())

            for a in range(len(nameList)):
                reference = externalNode["entryObject"][nameList[a]]
                resolved = self._resolve(reference)

                if resolved is not None and resolved.get("entryObject") is not None:
                    subtypeNode = self._resolve(resolved["entryObject"].get("Subtype"))

                    resultObject[nameList[a]] = {
                        "referenceNumber": reference["number"] if reference["kind"] == "reference" else 0,
                        "subtype": subtypeNode["value"] if subtypeNode is not None and subtypeNode["kind"] == "name" else "",
                        "width": self._numberValue(resolved["entryObject"].get("Width")),
                        "height": self._numberValue(resolved["entryObject"].get("Height"))
                    }

        return resultObject

    def _resourceState(self, resourceObject):
        resultObject = {}

        stateNode = self._resolve(resourceObject.get("ExtGState"))

        if stateNode is not None and stateNode["kind"] == "dictionary" and stateNode.get("entryObject") is not None:
            nameList = list(stateNode["entryObject"].keys())

            for a in range(len(nameList)):
                resolved = self._resolve(stateNode["entryObject"][nameList[a]])

                if resolved is not None and resolved.get("entryObject") is not None:
                    fontNode = self._resolve(resolved["entryObject"].get("Font"))

                    if fontNode is not None and fontNode["kind"] == "array" and fontNode.get("itemList") is not None and len(fontNode["itemList"]) == 2:
                        fontResolved = self._resolve(fontNode["itemList"][0])

                        if fontResolved is not None:
                            resultObject[nameList[a]] = {
                                "font": self._buildFont(fontResolved),
                                "fontSize": self._numberValue(fontNode["itemList"][1])
                            }

        return resultObject

    def _handleOperator(self, operator, stackList, stateObject, fontObject, externalObject):
        def number(indexFromEnd):
            result = 0

            if indexFromEnd >= 1 and indexFromEnd <= len(stackList):
                node = stackList[len(stackList) - indexFromEnd]

                if node["kind"] == "number":
                    result = node["value"]

            return result

        if operator == "cm":
            self.ctmList = self._matrixMultiply(self.ctmList, [number(6), number(5), number(4), number(3), number(2), number(1)])
        elif operator == "q":
            self.graphicsStateList.append({
                "ctmList": list(self.ctmList),
                "currentFont": self.currentFont,
                "fontSize": self.fontSize,
                "charSpacing": self.charSpacing,
                "wordSpacing": self.wordSpacing,
                "horizontalScale": self.horizontalScale,
                "leading": self.leading,
                "textRender": self.textRender,
                "textRise": self.textRise,
                "fillColor": self.fillColor,
                "strokeColor": self.strokeColor
            })
        elif operator == "Q":
            if len(self.graphicsStateList) > 0:
                stateObject = self.graphicsStateList.pop()

                self.ctmList = stateObject["ctmList"]
                self.currentFont = stateObject["currentFont"]
                self.fontSize = stateObject["fontSize"]
                self.charSpacing = stateObject["charSpacing"]
                self.wordSpacing = stateObject["wordSpacing"]
                self.horizontalScale = stateObject["horizontalScale"]
                self.leading = stateObject["leading"]
                self.textRender = stateObject["textRender"]
                self.textRise = stateObject["textRise"]
                self.fillColor = stateObject["fillColor"]
                self.strokeColor = stateObject["strokeColor"]
        elif operator == "BT":
            self.textMatrixList = [1, 0, 0, 1, 0, 0]
            self.lineMatrixList = [1, 0, 0, 1, 0, 0]
        elif operator == "Tf":
            nameNode = stackList[len(stackList) - 2] if len(stackList) >= 2 else None

            self.fontSize = number(1)

            if nameNode is not None and nameNode["kind"] == "name":
                self.currentFont = fontObject.get(nameNode["value"])
        elif operator == "Tr":
            self.textRender = int(number(1))
        elif operator == "Ts":
            self.textRise = number(1)
        elif operator == "gs":
            nameNode = stackList[len(stackList) - 1] if len(stackList) >= 1 else None

            if nameNode is not None and nameNode["kind"] == "name" and nameNode["value"] in stateObject:
                self.currentFont = stateObject[nameNode["value"]]["font"]
                self.fontSize = stateObject[nameNode["value"]]["fontSize"]
        elif operator == "Td":
            self.lineMatrixList = self._matrixMultiply(self.lineMatrixList, [1, 0, 0, 1, number(2), number(1)])
            self.textMatrixList = list(self.lineMatrixList)
        elif operator == "TD":
            self.leading = -number(1)
            self.lineMatrixList = self._matrixMultiply(self.lineMatrixList, [1, 0, 0, 1, number(2), number(1)])
            self.textMatrixList = list(self.lineMatrixList)
        elif operator == "Tm":
            self.lineMatrixList = [number(6), number(5), number(4), number(3), number(2), number(1)]
            self.textMatrixList = list(self.lineMatrixList)
        elif operator == "T*":
            self.lineMatrixList = self._matrixMultiply(self.lineMatrixList, [1, 0, 0, 1, 0, -self.leading])
            self.textMatrixList = list(self.lineMatrixList)
        elif operator == "Tc":
            self.charSpacing = number(1)
        elif operator == "Tw":
            self.wordSpacing = number(1)
        elif operator == "Tz":
            self.horizontalScale = number(1) / 100
        elif operator == "TL":
            self.leading = number(1)
        elif operator == "Tj" and self.currentFont is not None:
            if len(stackList) > 0:
                self._showText([stackList[len(stackList) - 1]], self.currentFont)
        elif operator == "TJ" and self.currentFont is not None:
            arrayNode = stackList[len(stackList) - 1] if len(stackList) > 0 else None

            if arrayNode is not None and arrayNode["kind"] == "array" and arrayNode.get("itemList") is not None:
                self._showText(arrayNode["itemList"], self.currentFont)
        elif (operator == "'" or operator == '"') and self.currentFont is not None:
            self.lineMatrixList = self._matrixMultiply(self.lineMatrixList, [1, 0, 0, 1, 0, -self.leading])
            self.textMatrixList = list(self.lineMatrixList)

            if len(stackList) > 0:
                self._showText([stackList[len(stackList) - 1]], self.currentFont)
        elif operator == "g":
            self.fillColor = self._colorRgb(number(1), number(1), number(1))
        elif operator == "G":
            self.strokeColor = self._colorRgb(number(1), number(1), number(1))
        elif operator == "rg":
            self.fillColor = self._colorRgb(number(3), number(2), number(1))
        elif operator == "RG":
            self.strokeColor = self._colorRgb(number(3), number(2), number(1))
        elif operator == "k":
            self.fillColor = self._colorRgb((1 - number(4)) * (1 - number(1)), (1 - number(3)) * (1 - number(1)), (1 - number(2)) * (1 - number(1)))
        elif operator == "K":
            self.strokeColor = self._colorRgb((1 - number(4)) * (1 - number(1)), (1 - number(3)) * (1 - number(1)), (1 - number(2)) * (1 - number(1)))
        elif operator == "m" or operator == "l" or operator == "c" or operator == "v" or operator == "y":
            self._pathAddPoint(number(2), number(1))
        elif operator == "re":
            x = number(4)
            y = number(3)
            width = number(2)
            height = number(1)
            wasEmpty = self.isPathEmpty

            self._pathAddPoint(x, y)
            self._pathAddPoint(x + width, y + height)

            self.isPathRectangle = wasEmpty
        elif operator == "f" or operator == "F" or operator == "f*":
            self._pathPaint(True, False)
        elif operator == "S" or operator == "s":
            self._pathPaint(False, True)
        elif operator == "B" or operator == "B*" or operator == "b" or operator == "b*":
            self._pathPaint(True, True)
        elif operator == "n":
            self._pathReset()
        elif operator == "Do":
            nameNode = stackList[len(stackList) - 1] if len(stackList) > 0 else None

            if nameNode is not None and nameNode["kind"] == "name":
                external = externalObject.get(nameNode["value"])

                if external is not None and external["subtype"] == "Image":
                    cornerAList = self._transformPoint(self.ctmList, 0, 0)
                    cornerBList = self._transformPoint(self.ctmList, 1, 1)

                    self.elementList.append({
                        "type": "image",
                        "x0": min(cornerAList[0], cornerBList[0]),
                        "y0": self.pageHeight - max(cornerAList[1], cornerBList[1]),
                        "x1": max(cornerAList[0], cornerBList[0]),
                        "y1": self.pageHeight - min(cornerAList[1], cornerBList[1]),
                        "referenceNumber": external["referenceNumber"]
                    })
        elif operator == "BI":
            endIndex = self.text.find("EI", self.position)

            self.position = endIndex + 2 if endIndex >= 0 else len(self.byteList)

    def _matrixMultiply(self, rightList, leftList):
        return [
            leftList[0] * rightList[0] + leftList[1] * rightList[2],
            leftList[0] * rightList[1] + leftList[1] * rightList[3],
            leftList[2] * rightList[0] + leftList[3] * rightList[2],
            leftList[2] * rightList[1] + leftList[3] * rightList[3],
            leftList[4] * rightList[0] + leftList[5] * rightList[2] + rightList[4],
            leftList[4] * rightList[1] + leftList[5] * rightList[3] + rightList[5]
        ]

    def _showText(self, partList, font):
        text = ""
        advanceStart = 0
        advance = 0

        for a in range(len(partList)):
            part = partList[a]

            if part["kind"] == "string" or part["kind"] == "hexString":
                decoded = self._fontDecode(part["value"], font)

                for b in range(len(decoded["charList"])):
                    text += decoded["charList"][b]

                    if font["isVertical"]:
                        code = decoded["codeList"][b]

                        fraction = font["verticalObject"][code] if font["isCidResolved"] and code in font["verticalObject"] else font["verticalFraction"]

                        advance += fraction * self.fontSize + self.charSpacing

                        continue

                    glyph = decoded["widthFractionList"][b] * self.fontSize + self.charSpacing

                    if font["byteLength"] == 1 and decoded["codeList"][b] == 32:
                        glyph += self.wordSpacing

                    advance += glyph * self.horizontalScale
            elif part["kind"] == "number":
                scale = self.fontSize * (1 if font["isVertical"] else self.horizontalScale)

                shift = -part["value"] / 1000 * scale

                if shift >= scale * self.levelTextShift:
                    self._textElementAppend(font, advanceStart, advance, text)

                    text = ""
                    advanceStart = advance + shift

                advance += shift

        self._textElementAppend(font, advanceStart, advance, text)

        self.textMatrixList = self._matrixMultiply(self.textMatrixList, [1, 0, 0, 1, 0, -advance] if font["isVertical"] else [1, 0, 0, 1, advance, 0])

    def _textElementAppend(self, font, advanceStart, advance, text):
        renderMatrixList = self._matrixMultiply(self.ctmList, self.textMatrixList)
        deviceFontSize = self.fontSize * math.hypot(renderMatrixList[2], renderMatrixList[3])

        if font["isVertical"]:
            cornerList = [
                self._transformPoint(renderMatrixList, -self.fontSize * 0.5, self.textRise - advanceStart),
                self._transformPoint(renderMatrixList, self.fontSize * 0.5, self.textRise - advanceStart),
                self._transformPoint(renderMatrixList, self.fontSize * 0.5, self.textRise - advance),
                self._transformPoint(renderMatrixList, -self.fontSize * 0.5, self.textRise - advance)
            ]
        else:
            cornerList = [
                self._transformPoint(renderMatrixList, advanceStart, self.textRise - self.fontSize * 0.2),
                self._transformPoint(renderMatrixList, advance, self.textRise - self.fontSize * 0.2),
                self._transformPoint(renderMatrixList, advance, self.textRise + self.fontSize * 0.8),
                self._transformPoint(renderMatrixList, advanceStart, self.textRise + self.fontSize * 0.8)
            ]

        bboxList = boxFromPointList(cornerList)

        if len(text.strip()) > 0 and self.textRender != 3 and self.textRender != 7:
            self.elementList.append({
                "type": "text",
                "text": text,
                "x0": bboxList[0],
                "y0": self.pageHeight - bboxList[3],
                "x1": bboxList[2],
                "y1": self.pageHeight - bboxList[1],
                "fontName": font["baseFont"],
                "fontSize": math.floor(deviceFontSize * 100 + 0.5) / 100,
                "isVertical": font["isVertical"],
                "isWidthEstimated": font["isWidthEstimated"],
                "color": self.fillColor
            })

    def _fontDecode(self, raw, font):
        charList = []
        widthFractionList = []
        codeList = []

        if font["codecName"] != "" and font["isUnicodeCode"] == False:
            decoder = codecs.getincrementaldecoder(font["codecName"])(errors="ignore")
            byteCount = 0

            for a in range(len(raw)):
                character = decoder.decode(bytes([ord(raw[a])]))
                byteCount += 1

                if len(character) > 0:
                    charList.append(character)
                    widthFractionList.append(font["defaultWidthFraction"] if byteCount > 1 else font["defaultWidthFraction"] / 2)
                    codeList.append(ord(raw[a]) if byteCount == 1 else 0)

                    byteCount = 0

            return {"charList": charList, "widthFractionList": widthFractionList, "codeList": codeList}

        for a in range(0, len(raw), font["byteLength"]):
            code = ord(raw[a])

            if font["byteLength"] == 2:
                code = (ord(raw[a]) << 8) | (ord(raw[a + 1]) if a + 1 < len(raw) else 0)

            character = font["toUnicodeObject"].get(code)

            if character is None and font["byteLength"] == 1:
                character = font["encodingObject"].get(code)

            if character is None:
                character = chr(code) if font["byteLength"] == 1 or font["isUnicodeCode"] else ""

            character = characterNormalize(character)

            widthFraction = font["defaultWidthFraction"]

            if font["byteLength"] == 2:
                if font["isCidResolved"] and font["widthObject"].get(code) is not None:
                    widthFraction = font["widthObject"][code]
            elif code >= font["firstChar"] and code - font["firstChar"] < len(font["widthList"]):
                widthFraction = font["widthList"][code - font["firstChar"]] * font["widthScale"]

            charList.append(character)
            widthFractionList.append(widthFraction)
            codeList.append(code)

        return {"charList": charList, "widthFractionList": widthFractionList, "codeList": codeList}

    def _transformPoint(self, matrixList, x, y):
        return [x * matrixList[0] + y * matrixList[2] + matrixList[4], x * matrixList[1] + y * matrixList[3] + matrixList[5]]

    def _colorRgb(self, red, green, blue):
        return f"#{self._componentHex(red)}{self._componentHex(green)}{self._componentHex(blue)}"

    def _componentHex(self, value):
        clamped = max(0, min(255, math.floor(value * 255 + 0.5)))

        return f"{clamped:02x}"

    def _pathAddPoint(self, x, y):
        pointList = self._transformPoint(self.ctmList, x, y)

        if self.isPathEmpty:
            self.pathMinX = pointList[0]
            self.pathMinY = pointList[1]
            self.pathMaxX = pointList[0]
            self.pathMaxY = pointList[1]
            self.isPathEmpty = False
        else:
            self.pathMinX = min(self.pathMinX, pointList[0])
            self.pathMinY = min(self.pathMinY, pointList[1])
            self.pathMaxX = max(self.pathMaxX, pointList[0])
            self.pathMaxY = max(self.pathMaxY, pointList[1])

    def _pathPaint(self, isFill, isStroke):
        if self.isPathEmpty == False:
            self.elementList.append({
                "type": "rect" if self.isPathRectangle else "path",
                "x0": self.pathMinX,
                "y0": self.pageHeight - self.pathMaxY,
                "x1": self.pathMaxX,
                "y1": self.pageHeight - self.pathMinY,
                "color": self.fillColor if isFill else self.strokeColor,
                "isFill": isFill,
                "isStroke": isStroke
            })

        self._pathReset()

    def execute(self, pathInput, password):
        with open(pathInput, "rb") as file:
            self.byteList = bytes(file.read())

        self.text = self._byteText(self.byteList)
        self.position = 0

        message = self._decryptBuild(password)

        if message != "":
            return {"message": message, "pageList": []}

        indirectList = self._parseIndirect()

        self.indirectObject = {}

        for a in range(len(indirectList)):
            self.indirectObject[indirectList[a]["number"]] = indirectList[a]

        pageList = self._buildPage()

        ideographPageResolve(pageList)

        return {"message": "", "pageList": pageList}

    def __init__(self):
        self.delimiterSet = set(ord(value) for value in "()<>[]{}/%")
        self.whitespaceSet = set([0, 9, 10, 12, 13, 32])
        self.digitSet = set(range(48, 58))
        self.numberSet = self.digitSet | set(ord(value) for value in "+-.")

        self.paddingByteList = bytes([0x28, 0xbf, 0x4e, 0x5e, 0x4e, 0x75, 0x8a, 0x41, 0x64, 0x00, 0x4e, 0x56, 0xff, 0xfa, 0x01, 0x08, 0x2e, 0x2e, 0x00, 0xb6, 0xd0, 0x68, 0x3e, 0x80, 0x2f, 0x0c, 0xa9, 0xfe, 0x64, 0x53, 0x69, 0x7a])

        self.versionEncryptList = [1, 2, 4, 5]

        self.levelTextShift = 0.4

        self.messageEncryption = "Encryption not supported."
        self.messagePasswordRequired = "Password required."
        self.messagePasswordWrong = "Password wrong."

        self.decryptObject = None
        self.isDecryptActive = False

        self.numberObject = 0
        self.generationObject = 0

        self.byteList = b""
        self.text = ""
        self.position = 0

        self.codecList = [
            ["UCS2", "utf-16-be"],
            ["UTF16", "utf-16-be"],
            ["RKSJ", "cp932"],
            ["GBK-EUC", "gbk"],
            ["GBpc-EUC", "gb2312"],
            ["GB-EUC", "gb2312"],
            ["KSCms-UHC", "cp949"],
            ["KSCpc-EUC", "cp949"],
            ["KSC-EUC", "euc_kr"],
            ["HKscs-B5", "big5hkscs"],
            ["ETen-B5", "big5"],
            ["B5pc", "big5"],
            ["EUC", "euc_jp"]
        ]

        self.indirectObject = {}
