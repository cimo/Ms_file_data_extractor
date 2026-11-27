import sys
import os
import cv2
import numpy
import io
import math

sys.dont_write_bytecode = True

# Source
from helper import onnxSessionBuild

class Recognition:
    def _imageCrop(self, coordinateList, image):
        pointList = numpy.array(coordinateList, dtype=numpy.float32)

        widthCrop = int(max(numpy.linalg.norm(pointList[0] - pointList[1]), numpy.linalg.norm(pointList[2] - pointList[3])))
        heightCrop = int(max(numpy.linalg.norm(pointList[0] - pointList[3]), numpy.linalg.norm(pointList[1] - pointList[2])))

        if widthCrop < 1 or heightCrop < 1:
            return None

        pointTargetList = numpy.array([
            [0, 0],
            [widthCrop, 0],
            [widthCrop, heightCrop],
            [0, heightCrop]
        ], dtype=numpy.float32)

        matrix = cv2.getPerspectiveTransform(pointList, pointTargetList)

        imageCrop = cv2.warpPerspective(
            image,
            matrix,
            (widthCrop, heightCrop),
            borderMode=cv2.BORDER_REPLICATE,
            flags=cv2.INTER_CUBIC
        )

        if heightCrop / float(widthCrop) >= self.ratioRotate:
            imageCrop = numpy.ascontiguousarray(numpy.rot90(imageCrop))

        return imageCrop

    def _batchGroup(self, indexList, imageCropList):
        resultList = []

        groupList = []
        ratioStart = 0.0

        for a in range(len(indexList)):
            ratio = imageCropList[indexList[a]].shape[1] / float(imageCropList[indexList[a]].shape[0])

            if len(groupList) >= self.sizeBatch or (len(groupList) > 0 and ratio > ratioStart * self.levelBatchRatio):
                resultList.append(groupList)

                groupList = []

            if len(groupList) == 0:
                ratioStart = ratio

            groupList.append(indexList[a])

        if len(groupList) > 0:
            resultList.append(groupList)

        return resultList

    def _textDecode(self, probability, widthColumn):
        indexList = probability.argmax(axis=-1)
        valueList = probability.max(axis=-1)

        text = ""
        scoreList = []
        positionList = []

        for a in range(len(indexList)):
            if indexList[a] == 0:
                continue

            if a > 0 and indexList[a] == indexList[a - 1]:
                positionList[len(positionList) - 1]["end"] = (a + 1) * widthColumn

                continue

            text += self.characterList[indexList[a]]

            scoreList.append(float(valueList[a]))

            positionList.append({"text": self.characterList[indexList[a]], "start": a * widthColumn, "end": (a + 1) * widthColumn, "alternativeList": [{"text": self.characterList[index], "probability": float(probability[a][index])} for index in sorted(numpy.flatnonzero(probability[a] >= self.levelAlternative), key=lambda index: -probability[a][index])[0:self.countAlternative] if index != 0]})

        score = 0.0

        if len(scoreList) > 0:
            score = float(numpy.mean(scoreList))

        return {
            "text": text,
            "score": score,
            "positionList": positionList
        }

    def execute(self, coordinateItemList, image):
        imageCropList = []

        for a in range(len(coordinateItemList)):
            imageCropList.append(self._imageCrop(coordinateItemList[a], image))

        indexList = []

        resultList = []

        for a in range(len(imageCropList)):
            resultList.append({"text": "", "score": 0.0, "positionList": []})

            if imageCropList[a] is not None:
                indexList.append(a)

        indexList.sort(key=lambda index: imageCropList[index].shape[1] / float(imageCropList[index].shape[0]))

        groupPageList = self._batchGroup(indexList, imageCropList)

        for a in range(len(groupPageList)):
            groupList = groupPageList[a]

            widthMax = self.imageWidthModel

            imageResizedList = []
            widthResizedList = []

            for b in range(len(groupList)):
                imageCrop = imageCropList[groupList[b]]

                widthResized = min(int(math.ceil(self.imageHeightModel * imageCrop.shape[1] / float(imageCrop.shape[0]))), self.imageWidthMax)

                widthMax = max(widthMax, widthResized)

                widthResizedList.append(widthResized)

                imageResizedList.append(cv2.resize(imageCrop, (widthResized, self.imageHeightModel)))

            widthMax = int(math.ceil(widthMax / float(self.imageWidthModel))) * self.imageWidthModel

            count = max(1, int(self.sizeBatch * self.imageWidthModel / widthMax))

            for b in range(0, len(imageResizedList), count):
                tensorBatch = numpy.zeros((count, 3, self.imageHeightModel, widthMax), dtype=numpy.float32)

                for c in range(len(imageResizedList[b:b + count])):
                    tensor = imageResizedList[b + c].astype(numpy.float32).transpose((2, 0, 1)) / 255.0
                    tensor = (tensor - 0.5) / 0.5

                    tensorBatch[c, :, :, 0:tensor.shape[2]] = tensor

                tensorOutputList = self.onnxSessionRecognition.run(None, {"x": tensorBatch})

                for c in range(len(imageResizedList[b:b + count])):
                    resultList[groupList[b + c]] = self._textDecode(tensorOutputList[0][c], widthMax / float(tensorOutputList[0][c].shape[0]) / widthResizedList[b + c])

        return resultList

    def __init__(self):
        self.pathModelRecognition = f"{os.path.dirname(os.path.abspath(__file__))}/model/paddle/PP-OCRv6_medium_rec/pp-ocrV6_medium_rec.onnx"
        self.pathDictionary = f"{os.path.dirname(os.path.abspath(__file__))}/model/paddle/PP-OCRv6_medium_rec/dictionary.txt"

        self.imageHeightModel = 48
        self.imageWidthModel = 320
        self.imageWidthMax = 3200

        self.ratioRotate = 1.5
        self.sizeBatch = 16

        self.countAlternative = 4
        self.levelAlternative = 0.02
        self.levelBatchRatio = 1.25

        self.characterList = ["blank"]

        lineList = io.open(self.pathDictionary, encoding="utf-8").read().split("\n")

        for a in range(len(lineList)):
            if lineList[a] != "":
                self.characterList.append(lineList[a])

        self.characterList.append(" ")

        self.onnxSessionRecognition = onnxSessionBuild(self.pathModelRecognition)
