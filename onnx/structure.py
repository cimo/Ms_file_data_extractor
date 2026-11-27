import sys
import os
import cv2
import numpy

sys.dont_write_bytecode = True

# Source
from helper import onnxSessionBuild

class Structure:
    def _tensorBuild(self, imageRgb):
        imageHeight, imageWidth = imageRgb.shape[0:2]

        ratio = self.imageSize / float(max(imageHeight, imageWidth))

        imageResized = cv2.resize(imageRgb, (max(1, int(round(imageWidth * ratio))), max(1, int(round(imageHeight * ratio)))), interpolation=cv2.INTER_LINEAR).astype(numpy.float32) / 255.0

        return numpy.expand_dims(((imageResized - self.normalizeMeanList) / self.normalizeStandardList).transpose((2, 0, 1)), axis=0).astype(numpy.float32)

    def _boxList(self, logit, box, classId, left, top, width, height, scale):
        resultList = []

        exponent = numpy.exp(logit - logit.max(axis=1, keepdims=True))

        score = exponent / exponent.sum(axis=1, keepdims=True)

        for a in range(score.shape[0]):
            if int(score[a].argmax()) != classId or score[a][classId] < self.scoreThreshold:
                continue

            centerX, centerY, boxWidth, boxHeight = box[a]

            resultList.append([(left + float(centerX - boxWidth / 2) * width) / scale, (top + float(centerY - boxHeight / 2) * height) / scale, (left + float(centerX + boxWidth / 2) * width) / scale, (top + float(centerY + boxHeight / 2) * height) / scale])

        return resultList

    def _boundaryList(self, boxList, indexStart, indexEnd):
        boxSortedList = sorted(boxList, key=lambda bboxList: bboxList[indexStart])

        return [(boxSortedList[a - 1][indexEnd] + boxSortedList[a][indexStart]) / 2 for a in range(1, len(boxSortedList))]

    def execute(self, image, scale, bboxList):
        left = max(0, int(round(bboxList[0] * scale)))
        top = max(0, int(round(bboxList[1] * scale)))

        imageRgb = cv2.cvtColor(image[top:int(round(bboxList[3] * scale)), left:int(round(bboxList[2] * scale))], cv2.COLOR_BGR2RGB)

        logit, box = self.onnxSession.run(None, {"pixel_values": self._tensorBuild(imageRgb)})

        return {
            "boundaryColumnList": self._boundaryList(self._boxList(logit[0], box[0], self.classColumn, left, top, imageRgb.shape[1], imageRgb.shape[0], scale), 0, 2),
            "boundaryRowList": self._boundaryList(self._boxList(logit[0], box[0], self.classRow, left, top, imageRgb.shape[1], imageRgb.shape[0], scale), 1, 3)
        }

    def __init__(self):
        self.imageSize = 800

        self.scoreThreshold = 0.5

        self.classColumn = 1
        self.classRow = 2

        self.normalizeMeanList = numpy.array([0.485, 0.456, 0.406], dtype=numpy.float32)
        self.normalizeStandardList = numpy.array([0.229, 0.224, 0.225], dtype=numpy.float32)

        self.onnxSession = onnxSessionBuild(f"{os.path.dirname(os.path.abspath(__file__))}/model/microsoft/table-transformer-structure-recognition-v1.1-all/model.onnx")
