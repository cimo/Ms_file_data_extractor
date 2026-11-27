import sys

sys.dont_write_bytecode = True

# Source
from helper import lineBuild, segmentBuild, blockText, textJoin, boxIntersection, boxCenterInsideCheck, boxExpand, boxArea, levelSpaceChar, levelSpaceWord, levelSpaceGap, levelLineOverlap, labelText, labelTitle, labelTable, labelForm, labelImage, labelHeader, labelPageList

class Region:
    def _itemRotate(self, textObject):
        bboxList = textObject["bbox"]

        result = dict(textObject)
        result["bboxSource"] = bboxList

        if textObject["isVertical"] or textObject["angle"] == 270:
            result["bbox"] = [bboxList[1], -bboxList[2], bboxList[3], -bboxList[0]]
        elif textObject["angle"] == 90:
            result["bbox"] = [-bboxList[3], bboxList[0], -bboxList[1], bboxList[2]]
        else:
            result["bbox"] = [-bboxList[2], -bboxList[3], -bboxList[0], -bboxList[1]]

        return result

    def _priorityCheck(self, regionObject, regionOtherObject):
        isTable = regionObject["label"] == labelTable

        if isTable != (regionOtherObject["label"] == labelTable):
            return isTable

        return regionObject["score"] > regionOtherObject["score"]

    def _regionFind(self, regionList, bboxList):
        result = None

        for a in range(len(regionList)):
            if regionList[a]["label"] != labelForm and boxCenterInsideCheck(bboxList, regionList[a]["bbox"]) and (result == None or self._priorityCheck(regionList[a], result)):
                result = regionList[a]

        if result != None:
            return result

        coverBest = 0

        for a in range(len(regionList)):
            if regionList[a]["label"] == labelForm:
                continue

            cover = boxIntersection(bboxList, regionList[a]["bbox"])

            if cover > coverBest or (cover > 0 and cover == coverBest and self._priorityCheck(regionList[a], result)):
                result = regionList[a]
                coverBest = cover

        return result

    def _bandList(self, pageObject, left, right):
        return [shapeObject["bbox"] for shapeObject in pageObject["shapeList"] if shapeObject["isCurve"] == False and shapeObject["bbox"][0] <= left + pageObject["size"] and shapeObject["bbox"][2] >= right - pageObject["size"]]

    def _bandItemList(self, pageObject, itemList):
        resultList = []

        bandList = self._bandList(pageObject, min(itemObject["bbox"][0] for itemObject in itemList), max(itemObject["bbox"][2] for itemObject in itemList))

        for a in range(len(bandList)):
            insideList = [itemObject for itemObject in itemList if boxCenterInsideCheck(itemObject["bbox"], bandList[a])]

            insideList.sort(key=lambda itemObject: itemObject["bbox"][0])

            if len(insideList) > 0 and len(lineBuild(insideList)) == 1 and len([b for b in range(1, len(insideList)) if insideList[b]["bbox"][0] - insideList[b - 1]["bbox"][2] >= insideList[b]["size"] * levelSpaceChar]) == 0:
                resultList += insideList

        return resultList

    def _bandOutsideList(self, regionList, bandItemList):
        resultList = []

        for a in range(len(regionList)):
            regionObject = regionList[a]

            if regionObject["label"] != labelTable:
                continue

            insideList = [itemObject for itemObject in regionObject["itemList"] if len([bandObject for bandObject in bandItemList if bandObject is itemObject]) > 0]
            restList = [itemObject for itemObject in regionObject["itemList"] if len([insideObject for insideObject in insideList if insideObject is itemObject]) == 0]

            if len(insideList) == 0 or len([itemObject for itemObject in restList if itemObject["bbox"][1] < max(insideObject["bbox"][3] for insideObject in insideList)]) > 0:
                continue

            regionObject["itemList"] = restList

            resultList += insideList

        return resultList

    def _lineCheck(self, bboxList, bboxOtherList):
        overlap = min(bboxList[3], bboxOtherList[3]) - max(bboxList[1], bboxOtherList[1])

        return overlap >= min(bboxList[3] - bboxList[1], bboxOtherList[3] - bboxOtherList[1]) * levelLineOverlap

    def _clusterFind(self, itemList, itemObject):
        lineList = sorted([itemOtherObject for itemOtherObject in itemList if self._lineCheck(itemOtherObject["bbox"], itemObject["bbox"])], key=lambda itemOtherObject: itemOtherObject["bbox"][0])

        start = [a for a in range(len(lineList)) if lineList[a] is itemObject][0]
        end = start

        for a in range(start, 0, -1):
            if lineList[a]["bbox"][0] - lineList[a - 1]["bbox"][2] >= lineList[a]["size"] * levelSpaceChar:
                break

            start = a - 1

        for a in range(end + 1, len(lineList)):
            if lineList[a]["bbox"][0] - lineList[a - 1]["bbox"][2] >= lineList[a]["size"] * levelSpaceChar:
                break

            end = a

        return lineList[start:end + 1]

    def _spanCheck(self, itemList, bboxList):
        return len([itemObject for itemObject in itemList if (itemObject["bbox"][0] + itemObject["bbox"][2]) / 2 < bboxList[0] or (itemObject["bbox"][0] + itemObject["bbox"][2]) / 2 > bboxList[2]]) == 0

    def _ruleBetweenCheck(self, itemObject, itemOtherObject, ruleList):
        bboxList = itemObject["bbox"]

        center = (bboxList[1] + bboxList[3]) / 2
        centerOther = (itemOtherObject["bbox"][1] + itemOtherObject["bbox"][3]) / 2

        for a in range(len(ruleList)):
            bboxRuleList = ruleList[a]["bbox"]

            if bboxRuleList[2] - bboxRuleList[0] < bboxRuleList[3] - bboxRuleList[1] or min(bboxRuleList[2], bboxList[2]) <= max(bboxRuleList[0], bboxList[0]):
                continue

            if (bboxRuleList[1] > center and bboxRuleList[1] < centerOther) or (bboxRuleList[3] > center and bboxRuleList[3] < centerOther):
                return True

        return False

    def _boxLabelFind(self, itemList, bboxList, ruleList):
        resultList = []

        baseList = [itemObject for itemObject in itemList if itemObject["bbox"][3] <= bboxList[1] + itemObject["size"] * levelSpaceGap and bboxList[1] - itemObject["bbox"][3] < itemObject["size"] * levelSpaceWord and self._spanCheck([itemObject], bboxList)]

        if len(baseList) == 0:
            return resultList

        clusterList = self._clusterFind(itemList, baseList[0])

        for a in range(len(itemList)):
            if self._spanCheck(clusterList, bboxList) == False:
                break

            resultList += clusterList

            top = min(itemObject["bbox"][1] for itemObject in clusterList)
            left = min(itemObject["bbox"][0] for itemObject in clusterList)
            right = max(itemObject["bbox"][2] for itemObject in clusterList)

            aboveList = [itemObject for itemObject in itemList if itemObject["bbox"][1] < top and top - itemObject["bbox"][3] < itemObject["size"] * levelSpaceWord and min(itemObject["bbox"][2], right) > max(itemObject["bbox"][0], left) and len([itemOtherObject for itemOtherObject in clusterList if self._lineCheck(itemObject["bbox"], itemOtherObject["bbox"])]) == 0 and self._ruleBetweenCheck(itemObject, clusterList[0], ruleList) == False]

            if len(aboveList) == 0:
                break

            clusterList = self._clusterFind(itemList, aboveList[0])

        return resultList

    def _boxList(self, pageObject):
        return [shapeObject["bbox"] for shapeObject in pageObject["shapeList"] if shapeObject["isCurve"] == False and min(shapeObject["bbox"][2] - shapeObject["bbox"][0], shapeObject["bbox"][3] - shapeObject["bbox"][1]) >= max(shapeObject["bbox"][2] - shapeObject["bbox"][0], shapeObject["bbox"][3] - shapeObject["bbox"][1]) * levelSpaceGap]

    def _boxLabelList(self, pageObject, itemList):
        resultList = []

        boxList = sorted(self._boxList(pageObject), key=lambda bboxList: boxArea(bboxList))

        restList = list(itemList)

        for a in range(len(boxList)):
            labelList = self._boxLabelFind(restList, boxList[a], pageObject["ruleList"])

            if len(labelList) > 0:
                resultList.append(labelList)

                restList = [itemObject for itemObject in restList if len([labelObject for labelObject in labelList if labelObject is itemObject]) == 0]

        return resultList, restList

    def _regionBuild(self, regionObject, itemList):
        bboxList = list(itemList[0]["bbox"])

        for a in range(1, len(itemList)):
            bboxList = boxExpand(bboxList, itemList[a]["bbox"])

        return {"label": regionObject["label"], "score": regionObject["score"], "bbox": bboxList, "itemList": itemList, "lineList": lineBuild(itemList), "rowList": [], "isRightFirst": False}

    def _lineRegionList(self, itemList):
        resultList = []

        lineList = lineBuild(itemList)

        for a in range(len(lineList)):
            resultList.append({"label": labelText, "score": 0.0, "bbox": list(lineList[a]["bbox"]), "itemList": lineList[a]["itemList"], "lineList": [lineList[a]], "rowList": [], "isRightFirst": False})

        return resultList

    def _ruleSplit(self, regionObject, ruleList):
        itemList = regionObject["itemList"]

        top = min(itemObject["bbox"][1] for itemObject in itemList)
        bottom = max(itemObject["bbox"][3] for itemObject in itemList)

        for a in range(len(ruleList)):
            bboxList = ruleList[a]["bbox"]

            if bboxList[2] - bboxList[0] >= bboxList[3] - bboxList[1] or bboxList[1] > top or bboxList[3] < bottom:
                continue

            leftList = [itemObject for itemObject in itemList if itemObject["bbox"][2] <= bboxList[2]]
            rightList = [itemObject for itemObject in itemList if itemObject["bbox"][0] >= bboxList[0]]

            if len(leftList) > 0 and len(rightList) > 0 and len(leftList) + len(rightList) == len(itemList):
                return self._ruleSplit(self._regionBuild(regionObject, leftList), ruleList) + self._ruleSplit(self._regionBuild(regionObject, rightList), ruleList)

        return [regionObject]

    def _ruleResolve(self, regionList, ruleList):
        resultList = []

        for a in range(len(regionList)):
            if regionList[a]["label"] in self.labelWholeList or len(regionList[a]["itemList"]) < 2:
                resultList.append(regionList[a])
            else:
                resultList += self._ruleSplit(regionList[a], ruleList)

        return resultList

    def _lineMerge(self, itemList, text):
        bboxList = list(itemList[0]["bbox"])

        for a in range(1, len(itemList)):
            bboxList = boxExpand(bboxList, itemList[a]["bbox"])

        return {"bbox": bboxList, "band": [bboxList[1], bboxList[3]], "itemList": itemList, "text": text}

    def _coverCheck(self, itemObject, itemOtherObject):
        bboxList = itemObject["bbox"]
        bboxOtherList = itemOtherObject["bbox"]

        return min(bboxList[3], bboxOtherList[3]) - max(bboxList[1], bboxOtherList[1]) >= (bboxOtherList[3] - bboxOtherList[1]) * levelLineOverlap

    def _stackCheck(self, regionObject, regionOtherObject):
        bboxList = regionObject["bbox"]
        bboxOtherList = regionOtherObject["bbox"]

        if bboxList[0] < bboxOtherList[0] or bboxList[2] > bboxOtherList[2]:
            return False

        itemList = regionOtherObject["itemList"]

        for a in range(len(itemList)):
            bboxItemList = itemList[a]["bbox"]

            if min(bboxItemList[2], bboxList[2]) <= max(bboxItemList[0], bboxList[0]) or self._lineCheck(bboxItemList, bboxList):
                continue

            for b in range(len(itemList)):
                if b != a and self._coverCheck(itemList[b], itemList[a]) and len([itemObject for itemObject in regionObject["itemList"] if self._coverCheck(itemList[b], itemObject) == False]) == 0:
                    return True

        return False

    def _stackResolve(self, regionList):
        lineList = [regionObject for regionObject in regionList if regionObject["label"] == labelText and regionObject["score"] == 0 and len(regionObject["lineList"]) == 1]

        for a in range(len(lineList)):
            for b in range(len(lineList)):
                if b != a and len(lineList[a]["itemList"]) > 0 and len(lineList[b]["itemList"]) > 0 and self._stackCheck(lineList[a], lineList[b]):
                    lineList[b]["itemList"] = lineList[b]["itemList"] + lineList[a]["itemList"]
                    lineList[b]["bbox"] = boxExpand(lineList[b]["bbox"], lineList[a]["bbox"])
                    lineList[b]["lineList"] = [self._lineMerge(lineList[b]["itemList"], blockText(lineList[b]["itemList"]))]

                    lineList[a]["itemList"] = []

                    break

        return [regionObject for regionObject in regionList if len([lineObject for lineObject in lineList if lineObject is regionObject and len(lineObject["itemList"]) == 0]) == 0]

    def _rotateRegionList(self, itemList, isRightFirst):
        resultList = []

        lineList = lineBuild(itemList)

        groupList = []

        for a in range(len(lineList)):
            size = lineList[a]["itemList"][0]["size"]

            isNear = a > 0 and lineList[a]["bbox"][1] - lineList[a - 1]["bbox"][3] < size * levelSpaceWord and min(lineList[a]["bbox"][2], lineList[a - 1]["bbox"][2]) > max(lineList[a]["bbox"][0], lineList[a - 1]["bbox"][0])
            isShift = a > 0 and abs(lineList[a]["bbox"][0] - lineList[a - 1]["bbox"][0]) >= size * levelSpaceWord

            if isNear == False or (isShift and len(groupList[len(groupList) - 1]) > 1):
                groupList.append([])

            groupList[len(groupList) - 1].append(lineList[a])

        for a in range(len(groupList)):
            groupItemList = [itemObject for lineObject in groupList[a] for itemObject in lineObject["itemList"]]

            text = ""

            for b in range(len(groupList[a])):
                text = textJoin(text, groupList[a][b]["text"])

            bboxList = list(groupItemList[0]["bboxSource"])

            for b in range(1, len(groupItemList)):
                bboxList = boxExpand(bboxList, groupItemList[b]["bboxSource"])

            resultList.append({"label": labelText, "score": 0.0, "bbox": bboxList, "itemList": groupItemList, "lineList": [self._lineMerge(groupItemList, text)], "rowList": [], "isRightFirst": isRightFirst})

        return resultList

    def _pageResolve(self, regionList):
        bodyList = [regionObject for regionObject in regionList if regionObject["label"] not in labelPageList and len(regionObject["itemList"]) > 0]

        for a in range(len(regionList)):
            regionObject = regionList[a]

            if regionObject["label"] not in labelPageList or len(regionObject["itemList"]) == 0:
                continue

            isBeyond = len([bodyObject for bodyObject in bodyList if (bodyObject["bbox"][3] <= regionObject["bbox"][1] if regionObject["label"] == labelHeader else bodyObject["bbox"][1] >= regionObject["bbox"][3])]) > 0
            isBeside = len([bodyObject for bodyObject in bodyList if bodyObject["score"] > 0 and min(bodyObject["bbox"][3], regionObject["bbox"][3]) > max(bodyObject["bbox"][1], regionObject["bbox"][1])]) > 0

            if isBeyond or isBeside:
                regionObject["label"] = labelText

    def _bandResolve(self, regionList, pageObject):
        textList = [regionObject for regionObject in regionList if len(regionObject["itemList"]) > 0]

        bandList = self._bandList(pageObject, min(regionObject["bbox"][0] for regionObject in textList), max(regionObject["bbox"][2] for regionObject in textList))

        for a in range(len(bandList)):
            insideList = [regionObject for regionObject in textList if boxCenterInsideCheck(regionObject["bbox"], bandList[a])]

            if len(insideList) == 1 and insideList[0]["label"] == labelText and len(insideList[0]["lineList"]) == 1:
                insideList[0]["label"] = labelTitle

    def _marginResolve(self, regionList, pageObject):
        textList = [regionObject for regionObject in regionList if len(regionObject["itemList"]) > 0]

        right = max(regionObject["bbox"][2] for regionObject in textList) - pageObject["size"]

        frameList = [bboxList for bboxList in self._boxList(pageObject) if bboxList[2] >= right]

        for a in range(len(textList)):
            regionObject = textList[a]
            bboxList = regionObject["bbox"]

            if regionObject["label"] != labelText or regionObject["isRightFirst"] or max(itemObject["size"] for itemObject in regionObject["itemList"]) <= pageObject["size"]:
                continue

            if len([regionOtherObject for regionOtherObject in textList if regionOtherObject["bbox"][2] <= bboxList[0] and min(regionOtherObject["bbox"][3], bboxList[3]) > max(regionOtherObject["bbox"][1], bboxList[1])]) > 0:
                continue

            for b in range(len(frameList)):
                if bboxList[2] > frameList[b][0] or bboxList[1] < frameList[b][1] or bboxList[3] > frameList[b][3]:
                    continue

                if len([regionOtherObject for regionOtherObject in textList if boxCenterInsideCheck(regionOtherObject["bbox"], frameList[b]) and min(regionOtherObject["bbox"][3], bboxList[3]) > max(regionOtherObject["bbox"][1], bboxList[1])]) > 0:
                    regionObject["label"] = labelTitle

                    break

    def execute(self, zoneList, pageObject):
        regionList = [{"label": zoneObject["label"], "score": zoneObject["score"], "bbox": zoneObject["bbox"], "itemList": [], "lineList": [], "rowList": [], "isRightFirst": False} for zoneObject in zoneList]

        outsideList = []
        uprightList = []

        rotateObject = {}

        for a in range(len(pageObject["textList"])):
            textObject = pageObject["textList"][a]

            if textObject["isVertical"] or textObject["angle"] != 0:
                key = (textObject["isVertical"], textObject["angle"])

                if key not in rotateObject:
                    rotateObject[key] = []

                rotateObject[key].append(self._itemRotate(textObject))
            else:
                uprightList.append(textObject)

        segmentList = segmentBuild(uprightList)

        for a in range(len(segmentList)):
            regionObject = self._regionFind(regionList, segmentList[a]["bbox"])

            if regionObject == None:
                outsideList.append(segmentList[a])
            else:
                regionObject["itemList"].append(segmentList[a])

        if len(segmentList) > 0:
            outsideList += self._bandOutsideList(regionList, self._bandItemList(pageObject, segmentList))

        for a in range(len(regionList)):
            regionList[a]["lineList"] = lineBuild(regionList[a]["itemList"])

        labelList, outsideList = self._boxLabelList(pageObject, outsideList)

        for a in range(len(labelList)):
            regionList.append(self._regionBuild({"label": labelText, "score": 0.0}, labelList[a]))

        regionList += self._lineRegionList(outsideList)

        regionList = self._stackResolve(self._ruleResolve(regionList, pageObject["ruleList"]))

        for key in rotateObject:
            regionList += self._rotateRegionList(rotateObject[key], key[0] or key[1] == 270)

        self._pageResolve(regionList)

        if len([regionObject for regionObject in regionList if len(regionObject["itemList"]) > 0]) > 0:
            self._bandResolve(regionList, pageObject)

            self._marginResolve(regionList, pageObject)

        return regionList

    def __init__(self):
        self.labelWholeList = [labelTable, labelImage]
