import sys

sys.dont_write_bytecode = True

# Source
from helper import boxArea, boxCenterInsideCheck, boxDistance, labelForm, labelImage, labelCaption, labelPageList, labelGraphicList

class Order:
    def _writeCheck(self, regionObject):
        return regionObject["label"] == labelForm or regionObject["label"] == labelImage or (len(regionObject["itemList"]) > 0 and regionObject["label"] not in labelPageList)

    def _insideList(self, regionList, regionObject):
        return [regionOtherObject for regionOtherObject in regionList if regionOtherObject is not regionObject and boxArea(regionOtherObject["bbox"]) < boxArea(regionObject["bbox"]) and boxCenterInsideCheck(regionOtherObject["bbox"], regionObject["bbox"])]

    def _frameCheck(self, regionObject, regionList):
        return regionObject["label"] != labelForm and len(regionObject["itemList"]) == 0 and len(self._insideList(regionList, regionObject)) > 0

    def _childAssign(self, regionList):
        resultList = []

        formList = [regionObject for regionObject in regionList if regionObject["label"] == labelForm]

        for a in range(len(formList)):
            formList[a]["childList"] = []

        for a in range(len(regionList)):
            regionObject = regionList[a]

            parentObject = None

            for b in range(len(formList)):
                formObject = formList[b]

                if formObject is regionObject or boxArea(formObject["bbox"]) <= boxArea(regionObject["bbox"]) or boxCenterInsideCheck(regionObject["bbox"], formObject["bbox"]) == False:
                    continue

                if parentObject == None or boxArea(formObject["bbox"]) < boxArea(parentObject["bbox"]):
                    parentObject = formObject

            if parentObject == None:
                resultList.append(regionObject)
            else:
                parentObject["childList"].append(regionObject)

        return resultList

    def _gapList(self, regionList, indexStart, indexEnd):
        resultList = []

        regionSortedList = sorted(regionList, key=lambda regionObject: regionObject["bbox"][indexStart])

        end = regionSortedList[0]["bbox"][indexEnd]

        for a in range(1, len(regionSortedList)):
            start = regionSortedList[a]["bbox"][indexStart]

            if start > end:
                resultList.append([end, start])

            end = max(end, regionSortedList[a]["bbox"][indexEnd])

        return resultList

    def _sideCheck(self, regionList, gap):
        leftList = [regionObject for regionObject in regionList if regionObject["bbox"][2] <= gap[0]]
        rightList = [regionObject for regionObject in regionList if regionObject["bbox"][0] >= gap[1]]

        for a in range(len(leftList)):
            for b in range(len(rightList)):
                if min(leftList[a]["bbox"][3], rightList[b]["bbox"][3]) > max(leftList[a]["bbox"][1], rightList[b]["bbox"][1]):
                    return True

        return False

    def _corridorList(self, regionList):
        return [gap for gap in self._gapList(regionList, 0, 2) if self._sideCheck(regionList, gap)]

    def _gapBest(self, gapList):
        result = None

        for a in range(len(gapList)):
            if result == None or gapList[a][1] - gapList[a][0] > result[1] - result[0]:
                result = gapList[a]

        return result

    def _split(self, regionList, index, limit):
        return [[regionObject for regionObject in regionList if regionObject["bbox"][index] < limit], [regionObject for regionObject in regionList if regionObject["bbox"][index] >= limit]]

    def _bandList(self, regionList):
        regionSortedList = sorted(regionList, key=lambda regionObject: regionObject["bbox"][1])

        resultList = [[regionSortedList[0]]]

        end = regionSortedList[0]["bbox"][3]

        for a in range(1, len(regionSortedList)):
            if regionSortedList[a]["bbox"][1] > end:
                resultList.append([])

            resultList[len(resultList) - 1].append(regionSortedList[a])

            end = max(end, regionSortedList[a]["bbox"][3])

        return resultList

    def _bandSideCheck(self, gapList, regionList):
        for a in range(len(gapList)):
            if len([regionObject for regionObject in regionList if regionObject["bbox"][2] <= gapList[a][0]]) > 0 and len([regionObject for regionObject in regionList if regionObject["bbox"][0] >= gapList[a][1]]) > 0:
                return True

        return False

    def _blockFind(self, bandList):
        result = None

        heightBest = 0

        for a in range(len(bandList)):
            regionList = []

            for b in range(a, len(bandList)):
                regionList = regionList + bandList[b]

                gapList = self._corridorList(regionList)

                if len(gapList) == 0:
                    break

                height = max(regionObject["bbox"][3] for regionObject in regionList) - min(regionObject["bbox"][1] for regionObject in regionList)

                if self._bandSideCheck(gapList, bandList[a]) and self._bandSideCheck(gapList, bandList[b]) and height > heightBest:
                    result = [a, b]

                    heightBest = height

        return result

    def _bandJoin(self, bandList):
        return [regionObject for a in range(len(bandList)) for regionObject in bandList[a]]

    def _overlapCheck(self, regionObject, regionOtherObject):
        return min(regionObject["bbox"][2], regionOtherObject["bbox"][2]) > max(regionObject["bbox"][0], regionOtherObject["bbox"][0])

    def _ruleGapFind(self, regionList, ruleList):
        top = min(regionObject["bbox"][1] for regionObject in regionList)
        bottom = max(regionObject["bbox"][3] for regionObject in regionList)

        gapList = self._corridorList(regionList)

        for a in range(len(gapList)):
            for b in range(len(ruleList)):
                bboxList = ruleList[b]["bbox"]

                if bboxList[2] - bboxList[0] < bboxList[3] - bboxList[1] and bboxList[0] >= gapList[a][0] and bboxList[2] <= gapList[a][1] and bboxList[1] <= top and bboxList[3] >= bottom:
                    return gapList[a]

        return None

    def _cut(self, regionList, isRowFirst, ruleList):
        if len(regionList) < 2:
            return regionList

        gapColumn = self._gapBest(self._corridorList(regionList))
        gapRow = self._gapBest(self._gapList(regionList, 1, 3))

        if gapColumn == None and gapRow == None:
            return sorted(regionList, key=lambda regionObject: (regionObject["bbox"][1], regionObject["bbox"][0]))

        if isRowFirst == False and gapColumn == None:
            bandList = self._bandList(regionList)

            block = self._blockFind(bandList)

            if block != None:
                return self._cut(self._bandJoin(bandList[0:block[0]]), isRowFirst, ruleList) + self._cut(self._bandJoin(bandList[block[0]:block[1] + 1]), isRowFirst, ruleList) + self._cut(self._bandJoin(bandList[block[1] + 1:]), isRowFirst, ruleList)

        isRow = gapRow != None if isRowFirst else gapColumn == None

        if isRow and isRowFirst and gapColumn != None:
            gapRule = self._ruleGapFind(regionList, ruleList)

            if gapRule != None:
                isRow = False

                gapColumn = gapRule

        gap = gapRow if isRow else gapColumn

        partList = self._split(regionList, 1 if isRow else 0, gap[1])

        return self._cut(partList[0], isRowFirst, ruleList) + self._cut(partList[1], isRowFirst, ruleList)

    def _expand(self, regionList, ruleList):
        resultList = []

        for a in range(len(regionList)):
            if regionList[a]["label"] == labelForm:
                resultList += self._expand(self._cut(regionList[a]["childList"], True, ruleList), ruleList)
            else:
                resultList.append(regionList[a])

        return resultList

    def _indexFind(self, regionList, regionObject):
        return [a for a in range(len(regionList)) if regionList[a] is regionObject][0]

    def _captionAttach(self, regionList):
        resultList = list(regionList)

        graphicList = [regionObject for regionObject in regionList if regionObject["label"] in labelGraphicList]

        for a in range(len(regionList)):
            regionObject = regionList[a]

            if regionObject["label"] != labelCaption or len(graphicList) == 0:
                continue

            graphicObject = min(graphicList, key=lambda graphicObject: (self._overlapCheck(regionObject, graphicObject) == False, boxDistance(regionObject["bbox"], graphicObject["bbox"])))

            index = self._indexFind(resultList, regionObject)
            indexGraphic = self._indexFind(resultList, graphicObject)

            if len([regionBetweenObject for regionBetweenObject in resultList[min(index, indexGraphic) + 1:max(index, indexGraphic)] if regionBetweenObject["label"] != labelCaption and regionBetweenObject["label"] not in labelGraphicList]) == 0:
                continue

            resultList.pop(index)

            resultList.insert(self._indexFind(resultList, graphicObject) + (1 if index > indexGraphic else 0), regionObject)

        return resultList

    def _frameInsert(self, regionList, frameList):
        resultList = list(regionList)

        frameSortedList = sorted(frameList, key=lambda regionObject: boxArea(regionObject["bbox"]))

        for a in range(len(frameSortedList)):
            insideList = self._insideList(resultList, frameSortedList[a])

            resultList.insert(min(self._indexFind(resultList, regionObject) for regionObject in insideList), frameSortedList[a])

        return resultList

    def _rightFirstResolve(self, regionList):
        resultList = []

        runList = []

        for a in range(len(regionList)):
            regionObject = regionList[a]

            isSide = len(runList) > 0 and regionObject["isRightFirst"] and min(regionObject["bbox"][3], runList[len(runList) - 1]["bbox"][3]) > max(regionObject["bbox"][1], runList[len(runList) - 1]["bbox"][1])

            if isSide == False:
                resultList += sorted(runList, key=lambda runObject: -runObject["bbox"][2])

                runList = []

            if regionObject["isRightFirst"]:
                runList.append(regionObject)
            else:
                resultList.append(regionObject)

        return resultList + sorted(runList, key=lambda runObject: -runObject["bbox"][2])

    def execute(self, regionList, ruleList):
        regionWriteList = [regionObject for regionObject in regionList if self._writeCheck(regionObject)]

        frameList = [regionObject for regionObject in regionWriteList if self._frameCheck(regionObject, regionWriteList)]

        resultList = self._expand(self._cut(self._childAssign([regionObject for regionObject in regionWriteList if len([frameObject for frameObject in frameList if frameObject is regionObject]) == 0]), False, ruleList), ruleList)

        return self._rightFirstResolve(self._captionAttach(self._frameInsert(resultList, frameList)))
