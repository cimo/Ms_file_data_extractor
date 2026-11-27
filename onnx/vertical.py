import sys
import os
import cv2
import numpy
import io
import unicodedata

sys.dont_write_bytecode = True

# Source
from helper import onnxSessionBuild, imageInkBuild, boxFromPointList, wideCheck, wideMarkCheck, textJoin, categoryWordList, levelSpaceChar, levelSpaceWord, levelLineOverlap, levelLineDouble

class Vertical:
    def _textRead(self, modelObject, imageCrop):
        imageResized = cv2.resize(imageCrop, (modelObject["width"], modelObject["height"]), interpolation=cv2.INTER_LINEAR)

        tensor = cv2.cvtColor(imageResized, cv2.COLOR_BGR2RGB).astype(numpy.float32).transpose((2, 0, 1)) / 127.5 - 1.0

        scoreList = modelObject["onnxSession"].run(None, {modelObject["name"]: tensor[numpy.newaxis]})[0][0]

        indexList = scoreList.argmax(axis=-1).tolist()

        count = indexList.index(0) if 0 in indexList else len(indexList)

        exponentList = numpy.exp(scoreList[0:count] - scoreList[0:count].max(axis=-1, keepdims=True))

        probabilityList = (exponentList / exponentList.sum(axis=-1, keepdims=True)).max(axis=-1)

        return {
            "text": "".join(self.characterList[index - 1] for index in indexList[0:count]),
            "score": float(probabilityList.mean()) if count > 0 else 0.0
        }

    def _narrowCheck(self, character):
        return wideCheck(character) == False and unicodedata.category(character)[0] in categoryWordList

    def _lineRead(self, imageLine):
        resultObject = {"text": "", "score": 0.0}

        for a in range(len(self.modelList)):
            if a < len(self.modelList) - 1 and imageLine.shape[1] / imageLine.shape[0] >= self.modelList[a]["count"] - self.countMargin:
                continue

            resultObject = self._textRead(self.modelList[a], imageLine)

            if len(resultObject["text"]) < self.modelList[a]["count"] - self.countMargin:
                break

        return resultObject

    def _runList(self, flagList, gap):
        resultList = []

        for a in range(len(flagList)):
            if flagList[a] and len(resultList) > 0 and a - resultList[len(resultList) - 1][1] < gap:
                resultList[len(resultList) - 1][1] = a + 1
            elif flagList[a]:
                resultList.append([a, a + 1])

        return resultList

    def _sideRead(self, imageColumn, imageInk, blockList):
        height, width = imageInk.shape[0:2]

        size = blockList[1] - blockList[0]

        columnList = imageInk[blockList[0]:blockList[1]].sum(axis=0)

        if size > width * self.levelSideHeight or len(self._runList((columnList > columnList.max() * self.levelSideInk).tolist(), 1)) < 2:
            return ""

        margin = int(size * self.levelSideMargin)

        imageBlock = imageColumn[max(0, blockList[0] - margin):min(height, blockList[1] + margin)]

        resultObject = self._textRead(self.modelList[0], imageBlock)

        text = resultObject["text"].strip()

        if len(text) < 2 or len([character for character in text if self._narrowCheck(character) == False]) > 0:
            return ""

        return text if resultObject["score"] > self._textRead(self.modelList[0], cv2.rotate(imageBlock, cv2.ROTATE_90_COUNTERCLOCKWISE))["score"] else ""

    def _segmentRead(self, imageColumn):
        resultObject = self._lineRead(cv2.rotate(imageColumn, cv2.ROTATE_90_COUNTERCLOCKWISE))

        if len([character for character in resultObject["text"] if self._narrowCheck(character)]) == 0:
            return resultObject

        imageInk = imageInkBuild(imageColumn)

        blockList = self._runList((imageInk.sum(axis=1) > 0).tolist(), imageColumn.shape[1] * self.levelSideGap)

        sideList = [self._sideRead(imageColumn, imageInk, blockList[a]) for a in range(len(blockList))]

        if len([text for text in sideList if text != ""]) == 0:
            return resultObject

        partList = []

        start = 0

        for a in range(len(blockList) + 1):
            if a < len(blockList) and sideList[a] == "":
                continue

            end = blockList[a][0] if a < len(blockList) else imageColumn.shape[0]

            if end > start and len([b for b in range(len(blockList)) if blockList[b][0] >= start and blockList[b][1] <= end]) > 0:
                partList.append(self._lineRead(cv2.rotate(imageColumn[start:end], cv2.ROTATE_90_COUNTERCLOCKWISE)))

            if a < len(blockList):
                partList.append({"text": sideList[a], "score": resultObject["score"]})

                start = blockList[a][1]

        return {"text": "".join(partObject["text"] for partObject in partList), "score": sum(partObject["score"] for partObject in partList) / len(partList)}

    def _blankResolve(self, text, imageColumn):
        imageInk = imageInkBuild(imageColumn)

        indexList = numpy.flatnonzero(imageInk.sum(axis=0) > 0)

        blockList = self._runList((imageInk.sum(axis=1) > 0).tolist(), (indexList[len(indexList) - 1] - indexList[0] + 1) * levelSpaceChar) if len(indexList) > 0 else []

        characterList = list(text)

        for a in range(1, len(blockList)):
            position = (blockList[a - 1][1] + blockList[a][0]) / 2 / imageColumn.shape[0] * len(characterList)

            for b in range(len(characterList)):
                if abs(b + 0.5 - position) < self.countBlankShift and unicodedata.category(characterList[b]) == "Pd" and wideCheck(characterList[b]) == False:
                    characterList[b] = " "

        return "".join(characterList)

    def _bandList(self, imageColumn, isDouble):
        columnList = imageInkBuild(imageColumn).sum(axis=0)

        runList = self._runList((columnList > columnList.max() * self.levelSideInk).tolist(), 1)

        sizeList = [runObject[1] - runObject[0] for runObject in runList]

        if len(runList) < 2:
            return [[0, imageColumn.shape[1]]]

        indexList = [a for a in range(len(runList)) if sizeList[a] > max(sizeList) * levelSpaceWord]

        if len(indexList) > 1 and isDouble == False:
            return [[0, imageColumn.shape[1]]]

        resultList = []

        for a in range(len(indexList) - 1, -1, -1):
            index = indexList[a]

            start = int((runList[index - 1][1] + runList[index][0]) / 2) if index > 0 else 0
            end = int((runList[index][1] + runList[index + 1][0]) / 2) if index < len(runList) - 1 else imageColumn.shape[1]

            resultList.append([start, end])

        return resultList

    def _coverCheck(self, bandList, coverList):
        return len([coverObject for coverObject in coverList if min(bandList[1], coverObject[1]) - max(bandList[0], coverObject[0]) >= (bandList[1] - bandList[0]) * levelLineOverlap]) > 0

    def _columnRead(self, imageColumn, isDouble, coverList):
        result = {"text": "", "score": 0.0}

        bandList = self._bandList(imageColumn, isDouble)

        bandList = [bandObject for bandObject in bandList if len(bandList) == 1 or self._coverCheck(bandObject, coverList) == False]

        for a in range(len(bandList)):
            imageBand = imageColumn[:, bandList[a][0]:bandList[a][1]]

            resultObject = self._segmentRead(imageBand)

            result["text"] = textJoin(result["text"], self._blankResolve(resultObject["text"], imageBand))
            result["score"] += resultObject["score"] / len(bandList)

        return result

    def _spaceCheck(self, text, index):
        if text[index].isspace() == False:
            return False

        sideList = [text[index - 1:index], text[index + 1:index + 2]]

        return len([character for character in sideList if wideMarkCheck(character)]) > 0 or len([character for character in sideList if wideCheck(character)]) == len(sideList)

    def _positionList(self, text):
        return [{"text": text[a], "start": a / len(text), "end": (a + 1) / len(text), "alternativeList": []} for a in range(len(text))]

    def _coverList(self, boxList, index, size):
        resultList = []

        bboxList = boxList[index]

        isTall = bboxList[3] - bboxList[1] >= bboxList[2] - bboxList[0]

        indexAcross = 0 if isTall else 1
        indexAlong = 1 - indexAcross

        for a in range(len(boxList)):
            bboxOtherList = boxList[a]

            overlap = min(bboxList[indexAlong + 2], bboxOtherList[indexAlong + 2]) - max(bboxList[indexAlong], bboxOtherList[indexAlong])

            if a == index or bboxOtherList[indexAcross + 2] - bboxOtherList[indexAcross] >= size or overlap < (bboxList[indexAlong + 2] - bboxList[indexAlong]) * levelLineOverlap:
                continue

            if isTall:
                resultList.append([bboxOtherList[0] - bboxList[0], bboxOtherList[2] - bboxList[0]])
            else:
                resultList.append([bboxList[3] - bboxOtherList[3], bboxList[3] - bboxOtherList[1]])

        return resultList

    def execute(self, coordinateItemList, image):
        resultList = []

        boxList = [boxFromPointList(coordinateList) for coordinateList in coordinateItemList]

        sizeList = sorted(min(bboxList[2] - bboxList[0], bboxList[3] - bboxList[1]) for bboxList in boxList)

        sizeDouble = sizeList[int(len(sizeList) / 2)] * levelLineDouble if len(sizeList) > 0 else 0

        for a in range(len(coordinateItemList)):
            bboxList = boxList[a]

            isDouble = min(bboxList[2] - bboxList[0], bboxList[3] - bboxList[1]) >= sizeDouble

            imageCrop = image[max(0, int(bboxList[1])):int(bboxList[3]), max(0, int(bboxList[0])):int(bboxList[2])]

            if imageCrop.shape[1] > imageCrop.shape[0]:
                imageCrop = cv2.rotate(imageCrop, cv2.ROTATE_90_CLOCKWISE)

            resultObject = self._columnRead(imageCrop, isDouble, self._coverList(boxList, a, sizeDouble) if isDouble else []) if imageCrop.shape[0] > 0 and imageCrop.shape[1] > 0 else {"text": "", "score": 0.0}

            resultObject["text"] = "".join(resultObject["text"][b] for b in range(len(resultObject["text"])) if self._spaceCheck(resultObject["text"], b) == False).strip()
            resultObject["positionList"] = self._positionList(resultObject["text"])

            resultList.append(resultObject)

        return resultList

    def __init__(self):
        pathModel = f"{os.path.dirname(os.path.abspath(__file__))}/model/ndl/PARSeq-tiny"

        self.locale = "ja"

        self.countMargin = 5
        self.countBlankShift = 2

        self.levelSideHeight = 0.75
        self.levelSideInk = 0.1
        self.levelSideGap = 0.1
        self.levelSideMargin = 0.5

        self.characterList = io.open(f"{pathModel}/dictionary.txt", encoding="utf-8", newline="").read().split("\n")

        self.modelList = []

        for count in [30, 50, 100]:
            onnxSession = onnxSessionBuild(f"{pathModel}/parseq-tiny_{count}.onnx")

            inputNode = onnxSession.get_inputs()[0]

            self.modelList.append({"onnxSession": onnxSession, "name": inputNode.name, "height": inputNode.shape[2], "width": inputNode.shape[3], "count": count})
