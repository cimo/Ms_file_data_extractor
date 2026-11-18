import sys
import os
import cv2
import numpy

sys.dont_write_bytecode = True

# Source
from helper import onnxSessionBuild, tensorNormalize, detrDetect, spacelessCheck, spaceSkipCheck, centerPointCalculate, boxCenterInsideCheck, boxArea, boxIntersection, boxIou, boxContainedRemove, rangeOverlapRatio, flowGapCalculate, levelBoxContained, levelBoxNms, levelSpaceGap, textCutCheck

class Table:
    def _collect(self, astPage):
        resultList = []

        itemList = astPage["itemList"]

        for a in range(len(itemList)):
            if itemList[a]["label"] == "table":
                resultList.append(itemList[a])

        return resultList

    def _interpolationChoose(self, imageRgb, width, height, interpolationEnlarge):
        imageHeight, imageWidth = imageRgb.shape[0:2]

        if width * height < imageWidth * imageHeight:
            return cv2.INTER_AREA

        return interpolationEnlarge

    def _typeClassify(self, imageRgb):
        imageHeight, imageWidth = imageRgb.shape[0:2]

        ratio = self.imageSizeShort / float(min(imageHeight, imageWidth))

        width = int(round(imageWidth * ratio))
        height = int(round(imageHeight * ratio))

        imageResized = cv2.resize(imageRgb, (width, height), interpolation=self._interpolationChoose(imageRgb, width, height, cv2.INTER_LINEAR))

        resizedHeight, resizedWidth = imageResized.shape[0:2]

        cropX = int(round((resizedWidth - self.imageSizeCrop) / 2))
        cropY = int(round((resizedHeight - self.imageSizeCrop) / 2))

        imageCrop = imageResized[cropY:cropY + self.imageSizeCrop, cropX:cropX + self.imageSizeCrop]

        tensor = tensorNormalize(imageCrop, self.normalizeMeanList, self.normalizeStdList)

        tensorOutputList = self.onnxSessionClassification.run(None, {"x": tensor})

        scoreList = tensorOutputList[0][0]

        index = int(numpy.argmax(scoreList))

        return {
            "type": self.labelList[index],
            "score": float(scoreList[index])
        }

    def _cellDetect(self, imageRgb, tableType):
        onnxSessionCell = self.onnxSessionCellWired if tableType == "wired" else self.onnxSessionCellWireless

        detectionList = detrDetect(imageRgb, self.imageSizeCell, self._interpolationChoose(imageRgb, self.imageSizeCell, self.imageSizeCell, cv2.INTER_CUBIC), onnxSessionCell)

        scoreThreshold = self.scoreThresholdCellWired if tableType == "wired" else self.scoreThresholdCellWireless

        resultList = []

        for a in range(len(detectionList)):
            if detectionList[a]["score"] < scoreThreshold:
                continue

            resultList.append({
                "score": detectionList[a]["score"],
                "coordinate": detectionList[a]["bbox"]
            })

        cellList = self._cellSuppression(resultList)
        cellList = self._cellContainedRemove(cellList)
        cellList = self._boxOverlapRemove(cellList)

        return cellList

    def _cellSuppression(self, boxList):
        resultList = []

        boxSortedList = sorted(boxList, key=lambda boxObject: boxObject["score"], reverse=True)

        for a in range(len(boxSortedList)):
            isOverlapped = False

            for b in range(len(resultList)):
                if boxIou(boxSortedList[a]["coordinate"], resultList[b]["coordinate"]) >= levelBoxNms:
                    isOverlapped = True

                    break

            if isOverlapped == False:
                resultList.append(boxSortedList[a])

        return resultList

    def _cellContainedRemove(self, cellList):
        resultList = []

        for a in range(len(cellList)):
            countContained = 0

            for b in range(len(cellList)):
                if a == b:
                    continue

                areaChild = boxArea(cellList[b]["coordinate"])

                if boxIntersection(cellList[a]["coordinate"], cellList[b]["coordinate"]) / float(areaChild) >= levelBoxContained:
                    countContained += 1

            if countContained < self.countContainedMinimum:
                resultList.append(cellList[a])

        return boxContainedRemove(resultList, "coordinate")

    def _boxOverlapRemove(self, boxList):
        resultList = []

        for a in range(len(boxList)):
            area = boxArea(boxList[a]["coordinate"])

            areaOverlap = 0

            for b in range(len(boxList)):
                if a == b or boxList[b]["score"] <= boxList[a]["score"]:
                    continue

                areaOverlap += boxIntersection(boxList[a]["coordinate"], boxList[b]["coordinate"])

            if areaOverlap / float(area) < self.levelBoxOverlap:
                resultList.append(boxList[a])

        return resultList

    def _medianValue(self, valueList):
        valueSortedList = sorted(valueList)

        return valueSortedList[int(len(valueSortedList) / 2)]

    def _cellRecover(self, imageRgb, cellList):
        coverageList = self._coverageCollect(imageRgb, cellList)

        resultList = []

        for a in range(len(cellList)):
            resultList.append(cellList[a])

        for a in range(len(coverageList)):
            resultList.append({"score": self.scoreCellRecovered, "coordinate": coverageList[a]})

        return resultList

    def _coverageCollect(self, imageRgb, cellList):
        if len(cellList) == 0:
            return []

        imageHeight, imageWidth = imageRgb.shape[0:2]

        imageMask = numpy.ones((imageHeight, imageWidth), dtype=numpy.uint8)

        heightList = []

        for a in range(len(cellList)):
            coordinateList = cellList[a]["coordinate"]

            imageMask[coordinateList[1]:coordinateList[3], coordinateList[0]:coordinateList[2]] = 0

            heightList.append(coordinateList[3] - coordinateList[1])

        sizeKernel = max(self.sizeCoverageKernel, int(round(self._medianValue(heightList) * self.levelCoverageKernel)))

        imageMask = cv2.morphologyEx(imageMask, cv2.MORPH_OPEN, numpy.ones((sizeKernel, sizeKernel), dtype=numpy.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)

        contourList = cv2.findContours(imageMask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]

        resultList = []

        for a in range(len(contourList)):
            if cv2.contourArea(contourList[a]) < imageWidth * imageHeight * self.levelCoverageArea:
                continue

            x, y, width, height = cv2.boundingRect(contourList[a])

            resultList.append([x, y, x + width, y + height])

        return self._coverageFilter(self._coverageSplit(resultList, cellList), cellList)

    def _coverageSplit(self, coverageList, cellList):
        resultList = []

        for a in range(len(coverageList)):
            coverageCoordinateList = coverageList[a]

            margin = max(self.marginCoverage, (coverageCoordinateList[2] - coverageCoordinateList[0]) * self.levelMarginCoverage)

            edgeList = []

            for b in range(len(cellList)):
                coordinateList = cellList[b]["coordinate"]

                for c in range(2):
                    edge = coordinateList[c * 2]

                    if edge > coverageCoordinateList[0] + margin and edge < coverageCoordinateList[2] - margin:
                        edgeList.append(edge)

            edgeList.sort()

            positionList = [coverageCoordinateList[0]]

            for b in range(len(edgeList)):
                if edgeList[b] - positionList[len(positionList) - 1] > margin:
                    positionList.append(edgeList[b])

            positionList.append(coverageCoordinateList[2])

            for b in range(len(positionList) - 1):
                resultList.append([positionList[b], coverageCoordinateList[1], positionList[b + 1], coverageCoordinateList[3]])

        return resultList

    def _coverageFilter(self, coverageList, cellList):
        widthList = []
        heightList = []

        for a in range(len(cellList)):
            coordinateList = cellList[a]["coordinate"]

            widthList.append(coordinateList[2] - coordinateList[0])
            heightList.append(coordinateList[3] - coordinateList[1])

        widthMinimum = self._medianValue(widthList) * self.levelCoverageSize
        heightMinimum = self._medianValue(heightList) * self.levelCoverageSize

        resultList = []

        for a in range(len(coverageList)):
            if coverageList[a][2] - coverageList[a][0] < widthMinimum or coverageList[a][3] - coverageList[a][1] < heightMinimum:
                continue

            resultList.append(coverageList[a])

        return resultList

    def _gridBuild(self, cellList, isCollision):
        if len(cellList) == 0:
            return cellList

        widthList = []
        heightList = []

        xList = []
        yList = []

        for a in range(len(cellList)):
            coordinateList = cellList[a]["coordinate"]

            widthList.append(coordinateList[2] - coordinateList[0])
            heightList.append(coordinateList[3] - coordinateList[1])

            xList.append(coordinateList[0])
            xList.append(coordinateList[2])

            yList.append(coordinateList[1])
            yList.append(coordinateList[3])

        toleranceColumn = self._medianValue(widthList) * self.levelGridTolerance
        toleranceRow = self._medianValue(heightList) * self.levelGridTolerance

        columnPositionList = self._positionFilter(self._positionCluster(xList, toleranceColumn), xList, toleranceColumn)
        rowPositionList = self._positionCluster(yList, toleranceRow)

        self._gridIndexAssign(cellList, columnPositionList, rowPositionList)

        columnCollisionList = []

        for a in range(len(cellList) if isCollision else 0):
            for b in range(len(cellList)):
                coordinateList = cellList[a]["coordinate"]
                coordinateOtherList = cellList[b]["coordinate"]

                if a == b or cellList[a]["rowIndex"] != cellList[b]["rowIndex"] or cellList[a]["columnIndex"] != cellList[b]["columnIndex"] or coordinateOtherList[0] < coordinateList[2] - toleranceColumn:
                    continue

                position = coordinateOtherList[0]

                if position not in columnPositionList and position not in columnCollisionList:
                    columnCollisionList.append(position)

        if len(columnCollisionList) > 0:
            self._gridIndexAssign(cellList, sorted(columnPositionList + columnCollisionList), rowPositionList)

        return sorted(cellList, key=lambda cellObject: (cellObject["rowIndex"], cellObject["columnIndex"]))

    def _gridIndexAssign(self, cellList, columnPositionList, rowPositionList):
        for a in range(len(cellList)):
            coordinateList = cellList[a]["coordinate"]

            columnIndex = self._positionIndex(coordinateList[0], columnPositionList)
            rowIndex = self._positionIndex(coordinateList[1], rowPositionList)

            cellList[a]["rowIndex"] = rowIndex
            cellList[a]["columnIndex"] = columnIndex
            cellList[a]["rowSpan"] = max(1, self._positionIndex(coordinateList[3], rowPositionList) - rowIndex)
            cellList[a]["columnSpan"] = max(1, self._positionIndex(coordinateList[2], columnPositionList) - columnIndex)

    def _rowLineMerge(self, cellList, imageRgb):
        countRow = 0

        for a in range(len(cellList)):
            countRow = max(countRow, cellList[a]["rowIndex"] + cellList[a]["rowSpan"])

        if countRow < 2:
            return cellList

        imageGray = cv2.cvtColor(imageRgb, cv2.COLOR_RGB2GRAY)

        countRuled = 0

        for a in range(1, countRow):
            if self._rowLineCheck(cellList, a, imageGray):
                countRuled += 1

        if countRuled < (countRow - 1) * self.levelRowRuled:
            return cellList

        cellObject = {}

        cellLastObject = {}

        for a in range(len(cellList)):
            columnIndex = cellList[a]["columnIndex"]

            key = (cellList[a]["rowIndex"], columnIndex)

            if columnIndex in cellLastObject and cellLastObject[columnIndex]["columnSpan"] == cellList[a]["columnSpan"] and self._cellLineCheck(cellList[a]["coordinate"], imageGray) == False:
                key = cellLastObject[columnIndex]["key"]

            if key in cellObject:
                cellObject[key]["score"] = max(cellObject[key]["score"], cellList[a]["score"])
                cellObject[key]["coordinate"] = [
                    min(cellObject[key]["coordinate"][0], cellList[a]["coordinate"][0]),
                    min(cellObject[key]["coordinate"][1], cellList[a]["coordinate"][1]),
                    max(cellObject[key]["coordinate"][2], cellList[a]["coordinate"][2]),
                    max(cellObject[key]["coordinate"][3], cellList[a]["coordinate"][3])
                ]
            else:
                cellObject[key] = {"score": cellList[a]["score"], "coordinate": list(cellList[a]["coordinate"])}

            cellLastObject[columnIndex] = {"key": key, "columnSpan": cellList[a]["columnSpan"]}

        return list(cellObject.values())

    def _rowLineCheck(self, cellList, rowIndex, imageGray):
        for a in range(len(cellList)):
            if cellList[a]["rowIndex"] == rowIndex and self._cellLineCheck(cellList[a]["coordinate"], imageGray):
                return True

        return False

    def _cellLineCheck(self, coordinateList, imageGray):
        tolerance = max(self.marginCoverage, int(round((coordinateList[3] - coordinateList[1]) * self.levelRowEdge)))

        region = imageGray[max(0, coordinateList[1] - tolerance):coordinateList[1] + tolerance, coordinateList[0]:coordinateList[2]]

        if region.size == 0:
            return False

        valueList = numpy.median(region, axis=1)

        return float(valueList.max() - valueList.min()) >= self.levelRowLine

    def _positionCluster(self, valueList, tolerance):
        resultList = []

        valueSortedList = sorted(valueList)

        for a in range(len(valueSortedList)):
            if len(resultList) > 0 and valueSortedList[a] - resultList[len(resultList) - 1] <= tolerance:
                continue

            resultList.append(valueSortedList[a])

        return resultList

    def _positionFilter(self, positionList, valueList, tolerance):
        countList = []

        for a in range(len(positionList)):
            count = 0

            for b in range(len(valueList)):
                if abs(valueList[b] - positionList[a]) <= tolerance:
                    count += 1

            countList.append(count)

        countMinimum = max(countList) * self.levelGridSupport

        resultList = []

        for a in range(len(positionList)):
            if countList[a] < countMinimum:
                continue

            resultList.append(positionList[a])

        return resultList

    def _positionIndex(self, value, positionList):
        indexNearest = 0
        distanceNearest = abs(value - positionList[0])

        for a in range(1, len(positionList)):
            distance = abs(value - positionList[a])

            if distance >= distanceNearest:
                continue

            indexNearest = a
            distanceNearest = distance

        return indexNearest

    def _textTableCollect(self, itemList, coordinateTableList):
        resultList = []

        for a in range(len(itemList)):
            if "isRotate" in itemList[a]:
                continue

            coordinateList = [
                itemList[a]["bbox"][0] - coordinateTableList[0],
                itemList[a]["bbox"][1] - coordinateTableList[1],
                itemList[a]["bbox"][2] - coordinateTableList[0],
                itemList[a]["bbox"][3] - coordinateTableList[1]
            ]

            if boxCenterInsideCheck(coordinateList, [0, 0, coordinateTableList[2] - coordinateTableList[0], coordinateTableList[3] - coordinateTableList[1]]) == False:
                continue

            resultList.append({"coordinate": coordinateList, "text": itemList[a]["text"]})

        return resultList

    def _cellColumnSplit(self, directionObject, cellList, textList, imageGray):
        resultList = []

        indexCross = 0 if directionObject["isVertical"] else 1
        indexFlow = 1 - indexCross

        for a in range(len(cellList)):
            coordinateList = cellList[a]["coordinate"]

            textInsideList = self._textInsideCollect(textList, coordinateList)

            if len(textInsideList) < 2:
                resultList.append(cellList[a])

                continue

            positionList = [coordinateList[indexFlow]]

            edgeList = sorted(self._columnEdgeCollect(cellList, a, indexCross, indexFlow) + self._columnRuleCollect(coordinateList, imageGray, indexFlow))

            for b in range(len(edgeList)):
                if self._columnBreakCheck(textInsideList, indexFlow, edgeList[b], positionList[len(positionList) - 1], coordinateList[indexFlow + 2]):
                    positionList.append(edgeList[b])

            positionList.append(coordinateList[indexFlow + 2])

            for b in range(len(positionList) - 1):
                coordinateSplitList = list(coordinateList)

                coordinateSplitList[indexFlow] = positionList[b]
                coordinateSplitList[indexFlow + 2] = positionList[b + 1]

                resultList.append({"score": cellList[a]["score"], "coordinate": coordinateSplitList})

        return resultList

    def _columnEdgeCollect(self, cellList, indexCell, indexCross, indexFlow):
        coordinateList = cellList[indexCell]["coordinate"]

        valueList = []

        for a in range(len(cellList)):
            if a == indexCell:
                continue

            coordinateOtherList = cellList[a]["coordinate"]

            if min(coordinateList[indexCross + 2], coordinateOtherList[indexCross + 2]) > max(coordinateList[indexCross], coordinateOtherList[indexCross]):
                continue

            for b in range(0, 3, 2):
                if coordinateOtherList[indexFlow + b] > coordinateList[indexFlow] and coordinateOtherList[indexFlow + b] < coordinateList[indexFlow + 2]:
                    valueList.append(coordinateOtherList[indexFlow + b])

        tolerance = (coordinateList[indexCross + 2] - coordinateList[indexCross]) * self.levelRowEdge

        resultList = []

        positionList = self._positionCluster(valueList, tolerance)

        for a in range(len(positionList)):
            count = 0

            for b in range(len(valueList)):
                if abs(valueList[b] - positionList[a]) <= tolerance:
                    count += 1

            if count >= self.countRowColumn:
                resultList.append(positionList[a])

        return resultList

    def _columnRuleCollect(self, coordinateList, imageGray, indexFlow):
        margin = self.marginCoverage

        region = imageGray[max(0, coordinateList[1] + margin):coordinateList[3] - margin, max(0, coordinateList[0] + margin):coordinateList[2] - margin]

        if region.size == 0:
            return []

        valueList = numpy.percentile(region, self.levelColumnRuled, axis=indexFlow)

        background = float(numpy.median(valueList))

        resultList = []

        indexStart = -1

        for a in range(len(valueList) + 1):
            isRuled = a < len(valueList) and background - float(valueList[a]) >= self.levelRowLine

            if isRuled and indexStart < 0:
                indexStart = a

            if isRuled == False and indexStart >= 0:
                if a - indexStart <= margin * self.countRuleWidth:
                    resultList.append(max(0, coordinateList[indexFlow] + margin) + (indexStart + a) // 2)

                indexStart = -1

        return resultList

    def _columnBreakCheck(self, textInsideList, indexFlow, edge, flowStart, flowEnd):
        isBefore = False
        isAfter = False

        for a in range(len(textInsideList)):
            coordinateList = textInsideList[a]["coordinate"]

            if coordinateList[indexFlow] < edge and coordinateList[indexFlow + 2] > edge:
                return False

            if coordinateList[indexFlow + 2] <= edge and coordinateList[indexFlow] >= flowStart:
                isBefore = True

            if coordinateList[indexFlow] >= edge and coordinateList[indexFlow + 2] <= flowEnd:
                isAfter = True

        return isBefore and isAfter

    def _cellSplit(self, directionObject, cellList, textList, tableType):
        resultList = []

        indexCross = 0 if directionObject["isVertical"] else 1

        for a in range(len(cellList)):
            coordinateList = cellList[a]["coordinate"]

            lineList = self._lineCoordinateGroup(self._textInsideCollect(textList, coordinateList), directionObject)

            if len(lineList) < 2:
                resultList.append(cellList[a])

                continue

            positionList = [coordinateList[indexCross]]

            for b in range(len(lineList) - 1):
                position = int(round((lineList[b]["cross2"] + lineList[b + 1]["cross1"]) / 2))

                if self._rowBreakCheck(directionObject, cellList, a, lineList[b], position, tableType, textList):
                    positionList.append(position)

            positionList.append(coordinateList[indexCross + 2])

            for b in range(len(positionList) - 1):
                if directionObject["isVertical"]:
                    resultList.append({"score": cellList[a]["score"], "coordinate": [positionList[b], coordinateList[1], positionList[b + 1], coordinateList[3]]})

                    continue

                resultList.append({"score": cellList[a]["score"], "coordinate": [coordinateList[0], positionList[b], coordinateList[2], positionList[b + 1]]})

        return resultList

    def _rowBreakCheck(self, directionObject, cellList, indexCell, lineObject, position, tableType, textList):
        indexCross = 0 if directionObject["isVertical"] else 1
        indexFlow = 1 - indexCross

        coordinateList = cellList[indexCell]["coordinate"]

        neighborList = []

        for a in range(len(cellList)):
            if a == indexCell:
                continue

            coordinateOtherList = cellList[a]["coordinate"]

            if min(coordinateList[indexCross + 2], coordinateOtherList[indexCross + 2]) <= max(coordinateList[indexCross], coordinateOtherList[indexCross]):
                continue

            if rangeOverlapRatio(coordinateList[indexFlow], coordinateList[indexFlow + 2], coordinateOtherList[indexFlow], coordinateOtherList[indexFlow + 2]) >= self.levelOverlapLine:
                continue

            neighborList.append(coordinateOtherList)

        if len(neighborList) == 0:
            return True

        tolerance = (lineObject["cross2"] - lineObject["cross1"]) * self.levelRowEdge

        for a in range(len(neighborList)):
            if abs(neighborList[a][indexCross] - position) <= tolerance or abs(neighborList[a][indexCross + 2] - position) <= tolerance:
                return True

        if tableType == "wired":
            return False

        countText = 0

        for a in range(len(neighborList)):
            lineNeighborList = self._lineCoordinateGroup(self._textInsideCollect(textList, neighborList[a]), directionObject)

            if len(lineNeighborList) == 0:
                continue

            countText += 1

            if lineNeighborList[0]["cross2"] > position or lineNeighborList[len(lineNeighborList) - 1]["cross1"] < position:
                return False

        return countText >= self.countRowColumn

    def _textInsideCollect(self, textList, cellCoordinateList):
        resultList = []

        for a in range(len(textList)):
            if boxCenterInsideCheck(textList[a]["coordinate"], cellCoordinateList) == False:
                continue

            resultList.append(textList[a])

        return resultList

    def _lineCoordinateGroup(self, textList, directionObject):
        resultList = []

        indexCross = 0 if directionObject["isVertical"] else 1

        textSortedList = sorted(textList, key=lambda textObject: textObject["coordinate"][indexCross])

        for a in range(len(textSortedList)):
            coordinateList = textSortedList[a]["coordinate"]

            cross1Text = coordinateList[indexCross]
            cross2Text = coordinateList[indexCross + 2]

            isAdded = False

            for b in range(len(resultList)):
                if rangeOverlapRatio(cross1Text, cross2Text, resultList[b]["cross1"], resultList[b]["cross2"]) < self.levelOverlapLine:
                    continue

                resultList[b]["cross1"] = min(resultList[b]["cross1"], cross1Text)
                resultList[b]["cross2"] = max(resultList[b]["cross2"], cross2Text)

                isAdded = True

                break

            if isAdded == False:
                resultList.append({"cross1": cross1Text, "cross2": cross2Text})

        return sorted(resultList, key=lambda lineObject: lineObject["cross1"])

    def _textOrphanAssign(self, textList, cellList):
        resultObject = {}

        for a in range(len(textList)):
            coordinateList = textList[a]["coordinate"]

            centerX = (coordinateList[0] + coordinateList[2]) / 2
            centerY = (coordinateList[1] + coordinateList[3]) / 2

            indexBest = -1
            distanceBest = -1

            isInside = False

            for b in range(len(cellList)):
                coordinateCellList = cellList[b]["coordinate"]

                if centerX >= coordinateCellList[0] and centerX <= coordinateCellList[2] and centerY >= coordinateCellList[1] and centerY <= coordinateCellList[3]:
                    isInside = True

                    break

                if centerY < coordinateCellList[1] or centerY > coordinateCellList[3]:
                    continue

                distance = max(coordinateCellList[0] - coordinateList[2], coordinateList[0] - coordinateCellList[2], 0)

                overlap = min(coordinateList[2], coordinateCellList[2]) - max(coordinateList[0], coordinateCellList[0])

                if overlap > 0:
                    distance = -overlap

                if indexBest < 0 or distance < distanceBest:
                    indexBest = b
                    distanceBest = distance

            if isInside or indexBest < 0:
                continue

            if indexBest not in resultObject:
                resultObject[indexBest] = []

            resultObject[indexBest].append(textList[a])

        return resultObject

    def _textCoordinateJoin(self, textList, directionObject):
        textSortedList = sorted(textList, key=lambda textObject: self._textOrderKey(textObject, directionObject))

        result = ""

        for a in range(len(textSortedList)):
            if len(result) == 0:
                result = textSortedList[a]["text"]

                continue

            if self._spaceCoordinateCheck(textSortedList[a - 1]["coordinate"], textSortedList[a]["coordinate"], result, textSortedList[a]["text"], directionObject):
                result += " "

            result += textSortedList[a]["text"]

        return result

    def _spaceCoordinateCheck(self, coordinatePreviousList, coordinateList, textPrevious, text, directionObject):
        if spaceSkipCheck(textPrevious, text):
            return False

        indexCross = 0 if directionObject["isVertical"] else 1

        if min(coordinatePreviousList[indexCross + 2], coordinateList[indexCross + 2]) <= max(coordinatePreviousList[indexCross], coordinateList[indexCross]):
            return spacelessCheck(textPrevious[-1:]) == False or spacelessCheck(text[0:1]) == False

        gapObject = flowGapCalculate(coordinatePreviousList, coordinateList, directionObject)

        return gapObject["gap"] >= gapObject["size"] * levelSpaceGap

    def _textOrderKey(self, textObject, directionObject):
        coordinateList = textObject["coordinate"]

        if directionObject["isVertical"]:
            return (-coordinateList[2], coordinateList[1])

        if directionObject["isRightToLeft"]:
            return (coordinateList[1], -coordinateList[2])

        return (coordinateList[1], coordinateList[0])

    def _coverageValidate(self, coverageList, textList):
        resultList = []

        for a in range(len(coverageList)):
            coverageCoordinateList = coverageList[a]

            isText = False

            for b in range(len(textList)):
                if boxCenterInsideCheck(textList[b]["coordinate"], coverageCoordinateList):
                    isText = True

                    break

            resultList.append({"coordinate": coverageCoordinateList, "isText": isText})

        return resultList

    def _textCutCollect(self, textList, cellList):
        resultList = []

        for a in range(len(textList)):
            coordinateList = textList[a]["coordinate"]

            for b in range(len(cellList)):
                if textCutCheck(coordinateList, cellList[b]["coordinate"]):
                    resultList.append(coordinateList)

                    break

        return resultList

    def _debugCell(self, image, coordinateList, cellList, coverageList, textCutList, pathOutput, numberPage, tableIndex, tableType):
        imageDebug = image[coordinateList[1]:coordinateList[3], coordinateList[0]:coordinateList[2]].copy()

        for a in range(len(cellList)):
            cellCoordinateList = cellList[a]["coordinate"]

            cv2.rectangle(imageDebug, (cellCoordinateList[0], cellCoordinateList[1]), (cellCoordinateList[2], cellCoordinateList[3]), self.colorCell, 1)

        for a in range(len(coverageList)):
            coverageCoordinateList = coverageList[a]["coordinate"]

            color = self.colorCoverage if coverageList[a]["isText"] else self.colorCoverageEmpty

            cv2.rectangle(imageDebug, (coverageCoordinateList[0], coverageCoordinateList[1]), (coverageCoordinateList[2], coverageCoordinateList[3]), color, 1)

        for a in range(len(textCutList)):
            cv2.rectangle(imageDebug, (textCutList[a][0], textCutList[a][1]), (textCutList[a][2], textCutList[a][3]), self.colorTextCut, 1)

        cv2.imwrite(f"{pathOutput}debug/table/{numberPage}_table{tableIndex}_{tableType}.jpg", imageDebug)

    def orderAssign(self, astPage, tableList):
        itemList = astPage["itemList"]

        indexObject = {}

        for a in range(len(itemList)):
            if itemList[a]["label"] == "table":
                indexObject[tuple(itemList[a]["bbox"])] = a

        tableList.sort(key=lambda tableObject: indexObject[tuple(tableObject["coordinate"])])

    def cellRefine(self, tableList, itemList, directionObject, image):
        for a in range(len(tableList)):
            coordinateList = tableList[a]["coordinate"]

            textList = self._textTableCollect(itemList, coordinateList)

            imageGray = cv2.cvtColor(image[coordinateList[1]:coordinateList[3], coordinateList[0]:coordinateList[2]], cv2.COLOR_BGR2GRAY)

            tableList[a]["cellList"] = self._rowSpanMerge(self._gridBuild(self._cellSplit(directionObject, self._cellColumnSplit(directionObject, tableList[a]["cellList"], textList, imageGray), textList, tableList[a]["type"]), True), textList)

    def _rowSpanMerge(self, cellList, textList):
        countRow = 0
        countColumn = 0

        for a in range(len(cellList)):
            countRow = max(countRow, cellList[a]["rowIndex"] + cellList[a]["rowSpan"])
            countColumn = max(countColumn, cellList[a]["columnIndex"] + cellList[a]["columnSpan"])

        if countRow < 2 or countColumn != self.countRowColumn:
            return cellList

        cellSpanList = []
        cellOtherList = []

        for a in range(len(cellList)):
            if cellList[a]["rowSpan"] == countRow:
                cellSpanList.append(cellList[a])
            else:
                cellOtherList.append(cellList[a])

        if len(cellSpanList) != 1 or len(cellOtherList) == 0 or len(self._textInsideCollect(textList, cellSpanList[0]["coordinate"])) == 0:
            return cellList

        coordinateList = list(cellOtherList[0]["coordinate"])
        score = cellOtherList[0]["score"]

        for a in range(1, len(cellOtherList)):
            coordinateOtherList = cellOtherList[a]["coordinate"]

            coordinateList = [
                min(coordinateList[0], coordinateOtherList[0]),
                min(coordinateList[1], coordinateOtherList[1]),
                max(coordinateList[2], coordinateOtherList[2]),
                max(coordinateList[3], coordinateOtherList[3])
            ]

            score = max(score, cellOtherList[a]["score"])

        return self._gridBuild([{"score": cellSpanList[0]["score"], "coordinate": cellSpanList[0]["coordinate"]}, {"score": score, "coordinate": coordinateList}], False)

    def textAssign(self, tableList, itemList, directionObject):
        for a in range(len(tableList)):
            textList = self._textTableCollect(itemList, tableList[a]["coordinate"])

            cellList = tableList[a]["cellList"]

            orphanObject = self._textOrphanAssign(textList, cellList)

            for b in range(len(cellList)):
                cellList[b]["text"] = self._textCoordinateJoin(self._textInsideCollect(textList, cellList[b]["coordinate"]) + orphanObject.get(b, []), directionObject)

            tableList[a]["cellList"] = self._rowEmptyRemove(cellList)

    def _rowEmptyRemove(self, cellList):
        rowKeepObject = {}

        for a in range(len(cellList)):
            rowIndex = cellList[a]["rowIndex"]

            if rowIndex not in rowKeepObject:
                rowKeepObject[rowIndex] = False

            if len(cellList[a]["text"].strip()) > 0 or cellList[a]["score"] != self.scoreCellRecovered:
                rowKeepObject[rowIndex] = True

        rowRemoveList = []

        for rowIndex in rowKeepObject:
            if rowKeepObject[rowIndex] == False:
                rowRemoveList.append(rowIndex)

        if len(rowRemoveList) == 0:
            return cellList

        resultList = []

        for a in range(len(cellList)):
            rowIndex = cellList[a]["rowIndex"]

            if rowIndex in rowRemoveList:
                continue

            countBefore = 0
            countInside = 0

            for b in range(len(rowRemoveList)):
                if rowRemoveList[b] < rowIndex:
                    countBefore += 1
                elif rowRemoveList[b] < rowIndex + cellList[a]["rowSpan"]:
                    countInside += 1

            cellList[a]["rowIndex"] = rowIndex - countBefore
            cellList[a]["rowSpan"] = cellList[a]["rowSpan"] - countInside

            resultList.append(cellList[a])

        return resultList

    def debugWrite(self, tableList, image, itemList, pathOutput, numberPage, countStart):
        if self.isDebug == False:
            return

        for a in range(len(tableList)):
            coordinateList = tableList[a]["coordinate"]

            imageRgb = cv2.cvtColor(image[coordinateList[1]:coordinateList[3], coordinateList[0]:coordinateList[2]], cv2.COLOR_BGR2RGB)

            cellList = tableList[a]["cellList"]

            textList = self._textTableCollect(itemList, coordinateList)

            coverageList = self._coverageValidate(self._coverageCollect(imageRgb, cellList), textList)

            textCutList = self._textCutCollect(textList, cellList)

            self._debugCell(image, coordinateList, cellList, coverageList, textCutList, pathOutput, numberPage, countStart + a + 1, tableList[a]["type"])

    def resultTableBuild(self, tablePageList, countStart, numberPage):
        resultList = []

        for a in range(len(tablePageList)):
            coordinateList = tablePageList[a]["coordinate"]

            cellList = tablePageList[a]["cellList"]

            cellResultList = []

            for b in range(len(cellList)):
                cellCoordinateList = cellList[b]["coordinate"]

                bboxList = [
                    cellCoordinateList[0] + coordinateList[0],
                    cellCoordinateList[1] + coordinateList[1],
                    cellCoordinateList[2] + coordinateList[0],
                    cellCoordinateList[3] + coordinateList[1]
                ]

                cellResultList.append({
                    "rowIndex": cellList[b]["rowIndex"],
                    "columnIndex": cellList[b]["columnIndex"],
                    "rowSpan": cellList[b]["rowSpan"],
                    "columnSpan": cellList[b]["columnSpan"],
                    "bbox": bboxList,
                    "centerPoint": centerPointCalculate(bboxList),
                    "text": cellList[b]["text"]
                })

            resultList.append({
                "id": countStart + len(resultList) + 1,
                "page": numberPage,
                "type": tablePageList[a]["type"],
                "bbox": coordinateList,
                "centerPoint": centerPointCalculate(coordinateList),
                "cellList": cellResultList
            })

        return resultList

    def execute(self, astPage, image):
        resultList = []

        tableList = self._collect(astPage)

        for a in range(len(tableList)):
            coordinateList = tableList[a]["bbox"]

            imageRgb = cv2.cvtColor(image[coordinateList[1]:coordinateList[3], coordinateList[0]:coordinateList[2]], cv2.COLOR_BGR2RGB)

            typeObject = self._typeClassify(imageRgb)

            cellList = self._cellDetect(imageRgb, typeObject["type"])
            cellList = self._cellRecover(imageRgb, cellList)
            cellList = self._gridBuild(cellList, False)

            if typeObject["type"] == "wired":
                cellList = self._gridBuild(self._rowLineMerge(cellList, imageRgb), False)

            resultList.append({
                "coordinate": coordinateList,
                "type": typeObject["type"],
                "cellList": cellList
            })

        return resultList

    def __init__(self, isDebug):
        self.isDebug = isDebug

        self.pathModelClassification = f"{os.path.dirname(__file__)}/model/pp-lcNet_x1_0_table_cls.onnx"
        self.pathModelCellWired = f"{os.path.dirname(__file__)}/model/rt-detr-l_wired_table_cell_det.onnx"
        self.pathModelCellWireless = f"{os.path.dirname(__file__)}/model/rt-detr-l_wireless_table_cell_det.onnx"

        self.countContainedMinimum = 2
        self.countRowColumn = 2
        self.sizeCoverageKernel = 3
        self.marginCoverage = 4

        self.imageSizeCell = 640
        self.imageSizeShort = 256
        self.imageSizeCrop = 224

        self.normalizeMeanList = numpy.array([0.485, 0.456, 0.406], dtype=numpy.float32)
        self.normalizeStdList = numpy.array([0.229, 0.224, 0.225], dtype=numpy.float32)

        self.levelBoxOverlap = 0.7
        self.levelCoverageArea = 0.002
        self.levelCoverageKernel = 0.4
        self.levelCoverageSize = 0.4
        self.levelMarginCoverage = 0.02
        self.levelOverlapLine = 0.5
        self.levelRowEdge = 0.5
        self.levelRowLine = 12
        self.levelColumnRuled = 90
        self.countRuleWidth = 4
        self.levelRowRuled = 0.5
        self.levelGridSupport = 0.25
        self.levelGridTolerance = 0.3

        self.scoreThresholdCellWired = 0.3
        self.scoreThresholdCellWireless = 0.15
        self.scoreCellRecovered = 0.0

        self.colorCell = (0, 200, 0)
        self.colorCoverage = (0, 0, 255)
        self.colorCoverageEmpty = (255, 0, 0)
        self.colorTextCut = (255, 0, 255)

        self.labelList = ["wired", "wireless"]

        self.onnxSessionClassification = onnxSessionBuild(self.pathModelClassification)
        self.onnxSessionCellWired = onnxSessionBuild(self.pathModelCellWired)
        self.onnxSessionCellWireless = onnxSessionBuild(self.pathModelCellWireless)
