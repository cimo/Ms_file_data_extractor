import sys
import os
import cv2
import numpy
import pyclipper

sys.dont_write_bytecode = True

# Source
from helper import onnxSessionBuild, tensorNormalize

class Detection:
    def _imageResize(self, image):
        imageHeight, imageWidth = image.shape[0:2]

        ratio = 1.0

        if max(imageHeight, imageWidth) > self.limitSideLength:
            if imageHeight > imageWidth:
                ratio = float(self.limitSideLength) / imageHeight
            else:
                ratio = float(self.limitSideLength) / imageWidth

        resizeHeight = int(imageHeight * ratio)
        resizeWidth = int(imageWidth * ratio)

        if max(resizeHeight, resizeWidth) > self.limitSideLengthMax:
            ratio = float(self.limitSideLengthMax) / max(resizeHeight, resizeWidth)

            resizeHeight = int(resizeHeight * ratio)
            resizeWidth = int(resizeWidth * ratio)

        resizeHeight = max(int(round(resizeHeight / 32) * 32), 32)
        resizeWidth = max(int(round(resizeWidth / 32) * 32), 32)

        return cv2.resize(image, (resizeWidth, resizeHeight))

    def _boxOrder(self, contour):
        rectangle = cv2.minAreaRect(contour)

        pointList = sorted(list(cv2.boxPoints(rectangle)), key=lambda point: point[0])

        index1 = 0
        index2 = 1
        index3 = 2
        index4 = 3

        if pointList[1][1] > pointList[0][1]:
            index1 = 0
            index4 = 1
        else:
            index1 = 1
            index4 = 0

        if pointList[3][1] > pointList[2][1]:
            index2 = 2
            index3 = 3
        else:
            index2 = 3
            index3 = 2

        return [pointList[index1], pointList[index2], pointList[index3], pointList[index4]], min(rectangle[1])

    def _boxScore(self, probabilityMap, box):
        mapHeight, mapWidth = probabilityMap.shape[0:2]

        boxLocal = box.copy()

        xMinimum = max(0, min(int(numpy.floor(box[:, 0].min())), mapWidth - 1))
        xMaximum = max(0, min(int(numpy.ceil(box[:, 0].max())), mapWidth - 1))
        yMinimum = max(0, min(int(numpy.floor(box[:, 1].min())), mapHeight - 1))
        yMaximum = max(0, min(int(numpy.ceil(box[:, 1].max())), mapHeight - 1))

        mask = numpy.zeros((yMaximum - yMinimum + 1, xMaximum - xMinimum + 1), dtype=numpy.uint8)

        boxLocal[:, 0] = boxLocal[:, 0] - xMinimum
        boxLocal[:, 1] = boxLocal[:, 1] - yMinimum

        cv2.fillPoly(mask, boxLocal.reshape(1, -1, 2).astype(numpy.int32), 1)

        return cv2.mean(probabilityMap[yMinimum:yMaximum + 1, xMinimum:xMaximum + 1], mask)[0]

    def _boxUnclip(self, box):
        area = cv2.contourArea(box)
        length = cv2.arcLength(box, True)

        distance = area * self.unclipRatio / length

        offsetObject = pyclipper.PyclipperOffset()

        offsetObject.AddPath(box, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)

        return numpy.array(offsetObject.Execute(distance))

    def _boxSort(self, itemList):
        return sorted(itemList, key=lambda item: (item["coordinate"][0][1], item["coordinate"][0][0]))

    def execute(self, image):
        resultList = []

        imageHeight, imageWidth = image.shape[0:2]
        imageResized = self._imageResize(image)

        tensor = tensorNormalize(imageResized, self.meanList, self.standardList)

        tensorOutputList = self.onnxSession.run(None, {"x": tensor})

        probabilityMap = tensorOutputList[0][0][0]
        bitmap = (probabilityMap > self.binaryThreshold).astype(numpy.uint8)

        scaleWidth = imageWidth / float(bitmap.shape[1])
        scaleHeight = imageHeight / float(bitmap.shape[0])

        contourList = cv2.findContours(bitmap * 255, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]

        for a in range(min(len(contourList), self.candidateMax)):
            pointList, sideLength = self._boxOrder(contourList[a])

            if sideLength < self.sideMinimum:
                continue

            score = self._boxScore(probabilityMap, numpy.array(pointList).reshape(-1, 2))

            if score < self.boxThreshold:
                continue

            pointList, sideLength = self._boxOrder(self._boxUnclip(numpy.array(pointList)).reshape(-1, 1, 2))

            if sideLength < self.sideMinimum + 2:
                continue

            coordinateList = []

            for b in range(len(pointList)):
                x = max(0, min(int(round(pointList[b][0] * scaleWidth)), imageWidth))
                y = max(0, min(int(round(pointList[b][1] * scaleHeight)), imageHeight))

                coordinateList.append([x, y])

            resultList.append({
                "score": float(score),
                "coordinate": coordinateList
            })

        return self._boxSort(resultList)

    def __init__(self):
        self.pathModel = f"{os.path.dirname(__file__)}/model/pp-ocrV6_medium_det.onnx"

        self.limitSideLength = 2000
        self.limitSideLengthMax = 4000
        self.binaryThreshold = 0.2
        self.boxThreshold = 0.45
        self.unclipRatio = 1.4
        self.candidateMax = 3000
        self.sideMinimum = 3

        self.meanList = numpy.array([0.485, 0.456, 0.406], dtype=numpy.float32)
        self.standardList = numpy.array([0.229, 0.224, 0.225], dtype=numpy.float32)

        self.onnxSession = onnxSessionBuild(self.pathModel)
