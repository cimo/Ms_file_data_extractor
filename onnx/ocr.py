import sys

sys.dont_write_bytecode = True

# Source
import detection
import recognition
from helper import boxFromPointList, centerPointCalculate, imageInkBuild, boxDebugWrite

class Ocr:
    def _verticalCheck(self, detectionList):
        countVertical = 0
        countHorizontal = 0

        for a in range(len(detectionList)):
            coordinateList = boxFromPointList(detectionList[a]["coordinate"])

            if coordinateList[3] - coordinateList[1] >= (coordinateList[2] - coordinateList[0]) * self.levelVerticalRatio:
                countVertical += 1
            else:
                countHorizontal += 1

        return countVertical > countHorizontal

    def _edgeInsideCollect(self, tableList, pointList, imageInk, isVertical):
        coordinateList = boxFromPointList(pointList)

        indexCross = 0 if isVertical else 1
        indexFlow = 1 if isVertical else 0

        center = (coordinateList[indexCross] + coordinateList[indexCross + 2]) / 2

        margin = (coordinateList[indexCross + 2] - coordinateList[indexCross]) * self.levelSplitMargin

        edgeList = []

        for a in range(len(tableList)):
            offsetCross = tableList[a]["coordinate"][indexCross]
            offsetFlow = tableList[a]["coordinate"][indexFlow]

            cellList = tableList[a]["cellList"]

            for b in range(len(cellList)):
                if center < cellList[b]["coordinate"][indexCross] + offsetCross or center > cellList[b]["coordinate"][indexCross + 2] + offsetCross:
                    continue

                edgeCellList = [cellList[b]["coordinate"][indexFlow] + offsetFlow, cellList[b]["coordinate"][indexFlow + 2] + offsetFlow]

                for c in range(len(edgeCellList)):
                    if edgeCellList[c] > coordinateList[indexFlow] + margin and edgeCellList[c] < coordinateList[indexFlow + 2] - margin:
                        edgeList.append(edgeCellList[c])

        edgeList.sort()

        resultList = []

        for a in range(len(edgeList)):
            if len(resultList) > 0 and edgeList[a] - resultList[len(resultList) - 1] <= margin:
                continue

            if self._edgeSplitCheck(coordinateList, edgeList[a], imageInk, isVertical) == False:
                continue

            resultList.append(edgeList[a])

        return resultList

    def _edgeSplitCheck(self, coordinateList, edge, imageInk, isVertical):
        indexCross = 0 if isVertical else 1

        cross0 = max(0, int(round(coordinateList[indexCross])))
        cross1 = min(imageInk.shape[1 if isVertical else 0], int(round(coordinateList[indexCross + 2])))

        size = cross1 - cross0

        if size <= 0:
            return False

        window = int(round(size * self.levelSplitMargin))

        flow0 = max(0, int(round(edge)) - window)
        flow1 = min(imageInk.shape[0 if isVertical else 1], int(round(edge)) + window + 1)

        if isVertical:
            ratioList = imageInk[flow0:flow1, cross0:cross1].sum(axis=1) / float(size)
        else:
            ratioList = imageInk[cross0:cross1, flow0:flow1].sum(axis=0) / float(size)

        gapMinimum = size * self.levelSplitGap
        gapCount = 0

        for a in range(len(ratioList)):
            if ratioList[a] >= self.levelSplitLine:
                return True

            if ratioList[a] == 0.0:
                gapCount += 1

                if gapCount >= gapMinimum:
                    return True
            else:
                gapCount = 0

        return False

    def _quadSplit(self, pointList, edgeList, isVertical):
        if len(edgeList) == 0:
            return [pointList]

        if isVertical:
            flowStart = min(pointList[0][1], pointList[1][1])
            flowEnd = max(pointList[3][1], pointList[2][1])
        else:
            flowStart = min(pointList[0][0], pointList[3][0])
            flowEnd = max(pointList[1][0], pointList[2][0])

        ratioList = [0.0]

        for a in range(len(edgeList)):
            ratioList.append((edgeList[a] - flowStart) / (flowEnd - flowStart))

        ratioList.append(1.0)

        resultList = []

        for a in range(len(ratioList) - 1):
            if isVertical:
                resultList.append([
                    self._pointInterpolate(pointList[0], pointList[3], ratioList[a]),
                    self._pointInterpolate(pointList[1], pointList[2], ratioList[a]),
                    self._pointInterpolate(pointList[1], pointList[2], ratioList[a + 1]),
                    self._pointInterpolate(pointList[0], pointList[3], ratioList[a + 1])
                ])

                continue

            resultList.append([
                self._pointInterpolate(pointList[0], pointList[1], ratioList[a]),
                self._pointInterpolate(pointList[0], pointList[1], ratioList[a + 1]),
                self._pointInterpolate(pointList[3], pointList[2], ratioList[a + 1]),
                self._pointInterpolate(pointList[3], pointList[2], ratioList[a])
            ])

        return resultList

    def _pointInterpolate(self, pointStart, pointEnd, ratio):
        return [
            pointStart[0] + (pointEnd[0] - pointStart[0]) * ratio,
            pointStart[1] + (pointEnd[1] - pointStart[1]) * ratio
        ]

    def boxDetect(self, image):
        return self.detection.execute(image)

    def execute(self, image, detectionList, tableList, countStart, numberPage, pathOutput):
        imageInk = imageInkBuild(image)

        isVertical = self._verticalCheck(detectionList)

        quadPageList = []

        for a in range(len(detectionList)):
            quadList = self._quadSplit(detectionList[a]["coordinate"], self._edgeInsideCollect(tableList, detectionList[a]["coordinate"], imageInk, isVertical), isVertical)

            for b in range(len(quadList)):
                quadPageList.append(quadList[b])

        recognitionList = self.recognition.execute(quadPageList, image)

        itemList = []
        coordinateItemList = []

        for a in range(len(quadPageList)):
            if len(recognitionList[a]["text"].strip()) == 0:
                continue

            coordinateList = boxFromPointList(quadPageList[a])

            itemList.append({
                "id": countStart + len(itemList) + 1,
                "page": numberPage,
                "bbox": [int(round(coordinateList[0])), int(round(coordinateList[1])), int(round(coordinateList[2])), int(round(coordinateList[3]))],
                "centerPoint": centerPointCalculate(coordinateList),
                "text": recognitionList[a]["text"]
            })

            coordinateItemList.append(itemList[len(itemList) - 1]["bbox"])

        if self.isDebug:
            boxDebugWrite(image, coordinateItemList, f"{pathOutput}debug/ocr/{numberPage}.jpg")

        return itemList

    def __init__(self, isDebug):
        self.isDebug = isDebug

        self.levelVerticalRatio = 2.0

        self.levelSplitMargin = 0.5
        self.levelSplitLine = 0.8
        self.levelSplitGap = 0.4

        self.detection = detection.Detection()
        self.recognition = recognition.Recognition()
