import sys
import math
import unicodedata
import numpy

sys.dont_write_bytecode = True

# Source
from helper import tokenScore, lineBuild, boxArea, boxCenterInsideCheck

class Spell:
    def _itemList(self, textList, regionList):
        groupList = [[] for a in range(len(regionList) + 1)]

        for a in range(len(textList)):
            indexList = sorted([b for b in range(len(regionList)) if boxCenterInsideCheck(textList[a]["bbox"], regionList[b]["bbox"])], key=lambda index: boxArea(regionList[index]["bbox"]))

            groupList[indexList[0] if len(indexList) > 0 else len(regionList)].append(textList[a])

        return [itemObject for a in range(len(groupList)) for lineObject in lineBuild(groupList[a]) for itemObject in lineObject["itemList"]]

    def _characterList(self, itemList):
        resultList = []

        for a in range(len(itemList)):
            resultList += [{"text": itemList[a]["text"][b], "alternativeList": itemList[a]["alternativeList"][b]} for b in range(len(itemList[a]["text"]))] + [{"text": " ", "alternativeList": []}]

        return resultList

    def _contextBuild(self, index, text):
        start = max(0, index - self.countToken)

        encodeObject = self.hyphen.tokenizer.encode(text[start:index + 1 + self.countToken])

        indexList = [a for a in range(len(encodeObject.ids)) if encodeObject.offsets[a][1] > encodeObject.offsets[a][0]]
        indexOwnList = [a for a in range(len(indexList)) if encodeObject.offsets[indexList[a]][0] <= index - start and encodeObject.offsets[indexList[a]][1] > index - start]

        if len(indexOwnList) == 0:
            return "", ""

        indexWindowList = indexList[max(0, indexOwnList[0] - self.countSide):indexOwnList[0] + self.countSide + 1]

        return text[start + encodeObject.offsets[indexWindowList[0]][0]:index], text[index + 1:start + encodeObject.offsets[indexWindowList[len(indexWindowList) - 1]][1]]

    def _rowObject(self, textBefore, character, textAfter):
        encodeObject = self.hyphen.tokenizer.encode(f"{textBefore}{character}{textAfter}")

        start = len(textBefore)
        end = start + len(character)

        indexList = [a for a in range(len(encodeObject.ids)) if len(encodeObject.ids) <= self.countToken and encodeObject.offsets[a][1] > encodeObject.offsets[a][0]]
        indexOwnList = [index for index in indexList if encodeObject.offsets[index][1] > start and encodeObject.offsets[index][0] < end]
        indexNearList = [index for index in indexList if len(indexOwnList) > 0 and index < indexOwnList[0]][-self.countNear:] + [index for index in indexList if len(indexOwnList) > 0 and index > indexOwnList[len(indexOwnList) - 1]][0:self.countNear]

        return {"ownList": [{"idList": encodeObject.ids, "index": index} for index in indexOwnList], "nearList": [{"idList": encodeObject.ids, "index": index} for index in indexNearList]}

    def _candidateList(self, index, text, alternativeList, character):
        resultList = []

        textBefore, textAfter = self._contextBuild(index, text)

        for a in range(len(alternativeList)):
            if alternativeList[a]["text"] != character and (alternativeList[a]["text"] == " " or unicodedata.normalize("NFKC", alternativeList[a]["text"]) == unicodedata.normalize("NFKC", character)):
                continue

            rowObject = self._rowObject(textBefore, alternativeList[a]["text"], textAfter)

            if len(rowObject["ownList"]) > 0:
                resultList.append({"text": alternativeList[a]["text"], "probability": alternativeList[a]["probability"], "rowObject": rowObject})

        return resultList

    def _scoreList(self, rowList):
        resultList = []

        for a in range(0, len(rowList), self.countBatch):
            rowBatchList = rowList[a:a + self.countBatch]

            tensor = numpy.full((self.countBatch, self.countToken), self.hyphen.idPad, dtype=numpy.int64)
            tensorMask = numpy.zeros((self.countBatch, self.countToken), dtype=numpy.int64)
            tensorIndex = numpy.zeros((self.countBatch, 1), dtype=numpy.int64)

            tensorMask[len(rowBatchList):, 0] = 1

            for b in range(len(rowBatchList)):
                tensor[b][0:len(rowBatchList[b]["idList"])] = rowBatchList[b]["idList"]
                tensor[b][rowBatchList[b]["index"]] = self.hyphen.idMask

                tensorMask[b][0:len(rowBatchList[b]["idList"])] = 1

                tensorIndex[b][0] = rowBatchList[b]["index"]

            output = self.hyphen.onnxSession.run(None, {"input_ids": tensor, "attention_mask": tensorMask, "mask_index": tensorIndex})[0]

            for b in range(len(rowBatchList)):
                resultList.append(tokenScore(output[b], rowBatchList[b]["idList"][rowBatchList[b]["index"]]))

        return resultList

    def _scoreWrite(self, candidateList, keyRow, keyScore):
        scoreList = self._scoreList([row for candidateObject in candidateList for row in candidateObject["rowObject"][keyRow]])

        index = 0

        for a in range(len(candidateList)):
            candidateList[a][keyScore] = sum(scoreList[index:index + len(candidateList[a]["rowObject"][keyRow])])

            index += len(candidateList[a]["rowObject"][keyRow])

    def _betterCheck(self, candidateList, character):
        currentList = [candidateObject for candidateObject in candidateList if candidateObject["text"] == character]

        return len(currentList) > 0 and len([candidateObject for candidateObject in candidateList if candidateObject["scoreOwn"] > currentList[0]["scoreOwn"]]) > 0

    def execute(self, textList, regionList):
        itemList = self._itemList(textList, regionList)

        characterList = self._characterList(itemList)

        resultList = [characterObject["text"] for characterObject in characterList]

        text = "".join(resultList)

        candidatePageList = [self._candidateList(a, text, characterList[a]["alternativeList"], resultList[a]) if len(characterList[a]["alternativeList"]) > 1 else [] for a in range(len(characterList))]

        self._scoreWrite([candidateObject for a in range(len(candidatePageList)) for candidateObject in candidatePageList[a]], "ownList", "scoreOwn")

        for a in range(len(candidatePageList)):
            if self._betterCheck(candidatePageList[a], resultList[a]) == False:
                continue

            candidateList = self._candidateList(a, "".join(resultList), characterList[a]["alternativeList"], resultList[a])

            self._scoreWrite(candidateList, "ownList", "scoreOwn")
            self._scoreWrite(candidateList, "nearList", "scoreNear")

            bestObject = [candidateObject for candidateObject in candidateList if candidateObject["text"] == resultList[a]][0]

            scoreOwn = bestObject["scoreOwn"]
            scoreNear = bestObject["scoreNear"]

            for b in range(len(candidateList)):
                if candidateList[b]["scoreOwn"] > scoreOwn and candidateList[b]["scoreNear"] > scoreNear and candidateList[b]["scoreOwn"] + candidateList[b]["scoreNear"] + math.log(candidateList[b]["probability"]) > bestObject["scoreOwn"] + bestObject["scoreNear"] + math.log(bestObject["probability"]):
                    bestObject = candidateList[b]

            resultList[a] = bestObject["text"]

        index = 0

        for a in range(len(itemList)):
            itemList[a]["text"] = "".join(resultList[index:index + len(itemList[a]["alternativeList"])])

            index += len(itemList[a]["alternativeList"]) + 1

    def __init__(self, hyphen):
        self.hyphen = hyphen

        self.countToken = hyphen.countToken
        self.countSide = int((self.countToken - 8) / 2)
        self.countNear = 3
        self.countBatch = 8
