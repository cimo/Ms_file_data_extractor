import sys
import cv2
import numpy

sys.dont_write_bytecode = True

# Source
from helper import boxFromPointList, boxArea, boxIntersection, imageInkBuild

class Watermark:
    def _heightBoxMedian(self, bboxList):
        sizeList = []

        for a in range(len(bboxList)):
            sizeList.append(min(bboxList[a][2] - bboxList[a][0], bboxList[a][3] - bboxList[a][1]))

        sizeList.sort()

        return sizeList[int(len(sizeList) / 2)]

    def _thresholdOtsu(self, valueList):
        return cv2.threshold(valueList.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0]

    def _levelBuild(self, imageGray):
        thresholdPage = self._thresholdOtsu(imageGray)

        background = float(numpy.median(imageGray[imageGray > thresholdPage]))

        thresholdInk = self._thresholdOtsu(imageGray[imageGray < background * self.levelBackground])

        thresholdDark = self._thresholdOtsu(imageGray[imageGray < thresholdInk])

        return {"thresholdPage": thresholdPage, "background": background, "thresholdDark": thresholdDark}

    def _middleBuild(self, imageGray, levelObject):
        return ((imageGray > levelObject["thresholdDark"]) & (imageGray < levelObject["background"] * self.levelBackground)).astype(numpy.uint8) * 255

    def _coreBuild(self, imageGrainless, levelObject, sizeCore, imageGray, height):
        core = cv2.morphologyEx(self._middleBuild(imageGrainless, levelObject), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (sizeCore, sizeCore)))

        count, labelMap, statList, _ = cv2.connectedComponentsWithStats(core, connectivity=8)

        whiteCountList = numpy.bincount(labelMap.ravel(), weights=(imageGray >= levelObject["background"] * self.levelBackground).ravel(), minlength=count)
        pixelCountList = numpy.bincount(labelMap.ravel(), minlength=count)

        isTextList = (whiteCountList > pixelCountList * self.levelCoreWhite) | (numpy.maximum(statList[:, 2], statList[:, 3]) < height)
        isTextList[0] = False

        core[isTextList[labelMap]] = 0

        return core

    def _coreGrow(self, imageGray, levelObject, sizeGrain, imageGrainless, core, height):
        middleClosed = cv2.morphologyEx(self._middleBuild(imageGray, levelObject), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (sizeGrain, sizeGrain))) | self._middleBuild(imageGrainless, levelObject)

        coreGrown = core.copy()

        for a in range(int(round(height * self.levelGrow))):
            coreGrown = cv2.dilate(coreGrown, numpy.ones((3, 3), numpy.uint8)) & middleClosed

        return coreGrown

    def _zoneBuild(self, height, coreGrown, core):
        sizeZone = max(3, int(round(height * self.levelZone)) | 1)

        zone = cv2.morphologyEx(coreGrown, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (sizeZone * 2 + 1, sizeZone * 2 + 1)))
        zone = cv2.dilate(zone, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (sizeZone, sizeZone)))

        coreDistance = cv2.distanceTransform((core > 0).astype(numpy.uint8), cv2.DIST_L2, 5)

        count, labelMap, statList, _ = cv2.connectedComponentsWithStats(zone, connectivity=8)

        strokeList = numpy.zeros(count)

        numpy.maximum.at(strokeList, labelMap.ravel(), coreDistance.ravel() * 2)

        sideList = numpy.minimum(statList[:, 2], statList[:, 3])

        isKeepList = (sideList >= height * self.levelZoneSize) & (strokeList <= sideList * self.levelZoneStroke)
        isKeepList[0] = False

        return isKeepList[labelMap].astype(numpy.uint8) * 255

    def _distanceTint(self, image, core, imageGray, levelObject):
        imageLab = cv2.cvtColor(image.astype(numpy.float32) / 255, cv2.COLOR_BGR2Lab)

        colorWatermark = numpy.median(imageLab[core > 0], axis=0)
        colorBackground = numpy.median(imageLab[imageGray > levelObject["thresholdPage"]], axis=0)

        axis = colorBackground - colorWatermark
        offset = imageLab - colorWatermark

        position = (offset @ axis) / float(axis @ axis)

        return numpy.clip(numpy.round(numpy.linalg.norm(offset - position[:, :, None] * axis, axis=2)), 0, 255).astype(numpy.uint8)

    def _ruleBuild(self, imageGray, core, levelObject, height):
        grayWatermark = float(numpy.median(imageGray[core > 0]))

        inkRule = (imageGray < (levelObject["thresholdDark"] + grayWatermark) / 2).astype(numpy.uint8) * 255

        length = max(1, int(round(height * self.levelRuleLength)))

        return cv2.morphologyEx(inkRule, cv2.MORPH_OPEN, numpy.ones((1, length), numpy.uint8)) | cv2.morphologyEx(inkRule, cv2.MORPH_OPEN, numpy.ones((length, 1), numpy.uint8))

    def _cleanBuild(self, image, core, imageGray, levelObject, zone, height, coreGrown, sizeCore):
        distance = self._distanceTint(image, core, imageGray, levelObject)

        thresholdTint = self._thresholdOtsu(distance[zone > 0])

        isToneMap = (imageGray > levelObject["thresholdDark"]) & (distance <= thresholdTint)

        rule = self._ruleBuild(imageGray, core, levelObject, height)

        body = cv2.dilate(coreGrown, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (sizeCore, sizeCore)))

        textRing = cv2.dilate((imageGray <= levelObject["thresholdDark"]).astype(numpy.uint8), numpy.ones((3, 3), numpy.uint8))

        imageClean = imageGray.copy()

        imageClean[(body > 0) & isToneMap & (rule == 0) & (textRing == 0)] = 255
        imageClean[(zone > 0) & (imageGray >= levelObject["background"] * self.levelBackground) & (distance <= thresholdTint)] = 255

        count, labelMap, statList, _ = cv2.connectedComponentsWithStats((imageClean < levelObject["background"] * self.levelBackground).astype(numpy.uint8), connectivity=8)

        isSpeckList = numpy.zeros(count, bool)
        isSpeckList[1:] = numpy.maximum(statList[1:, 2], statList[1:, 3]) < height * self.levelSpeck

        imageClean[isSpeckList[labelMap]] = 255

        return imageClean

    def _zoneCheck(self, zone, bboxList):
        return bool(zone[int(bboxList[1]):int(bboxList[3]) + 1, int(bboxList[0]):int(bboxList[2]) + 1].any())

    def _overlapCheck(self, bboxList, bboxOtherList):
        return bboxList[0] < bboxOtherList[2] and bboxOtherList[0] < bboxList[2] and bboxList[1] < bboxOtherList[3] and bboxOtherList[1] < bboxList[3]

    def _rowSameCheck(self, bboxList, bboxOtherList, levelOverlap):
        overlap = min(bboxList[3], bboxOtherList[3]) - max(bboxList[1], bboxOtherList[1])

        return overlap >= min(bboxList[3] - bboxList[1], bboxOtherList[3] - bboxOtherList[1]) * levelOverlap

    def _heightSimilarCheck(self, bboxList, bboxOtherList):
        return abs((bboxOtherList[3] - bboxOtherList[1]) - (bboxList[3] - bboxList[1])) <= (bboxList[3] - bboxList[1]) * self.levelRowHeight

    def _pointBuild(self, bboxList):
        return [[bboxList[0], bboxList[1]], [bboxList[2], bboxList[1]], [bboxList[2], bboxList[3]], [bboxList[0], bboxList[3]]]

    def _cleanCollect(self, detectionCleanList, bboxKeepList, zone, bboxDropList):
        resultList = []

        for a in range(len(detectionCleanList)):
            bboxList = boxFromPointList(detectionCleanList[a]["coordinate"])

            area = boxArea(bboxList)

            isDuplicate = False

            for b in range(len(bboxKeepList)):
                if boxIntersection(bboxList, bboxKeepList[b]) >= area * self.levelDuplicate:
                    isDuplicate = True

                    break

            if isDuplicate:
                continue

            isReplace = self._zoneCheck(zone, bboxList)

            for b in range(len(bboxDropList)):
                if isReplace:
                    break

                isReplace = self._overlapCheck(bboxList, bboxDropList[b])

            if isReplace:
                resultList.append(detectionCleanList[a])

        return resultList

    def _cleanExtend(self, detectionCleanList, bboxDropList, height):
        bboxCleanList = []

        for a in range(len(detectionCleanList)):
            bboxCleanList.append(boxFromPointList(detectionCleanList[a]["coordinate"]))

        for a in range(len(detectionCleanList)):
            bboxList = bboxCleanList[a]

            for b in range(len(bboxDropList)):
                if not self._overlapCheck(bboxList, bboxDropList[b]) or not self._heightSimilarCheck(bboxList, bboxDropList[b]) or not self._rowSameCheck(bboxList, bboxDropList[b], self.levelRowOverlap):
                    continue

                left = min(bboxList[0], bboxDropList[b][0])
                right = max(bboxList[2], bboxDropList[b][2])

                for c in range(len(detectionCleanList)):
                    if c == a or not self._rowSameCheck(bboxList, bboxCleanList[c], self.levelDuplicate) or not self._heightSimilarCheck(bboxList, bboxCleanList[c]):
                        continue

                    if bboxCleanList[c][0] < bboxList[0] and bboxCleanList[c][2] > left:
                        left = max(left, bboxCleanList[c][2])

                    if bboxCleanList[c][2] > bboxList[2] and bboxCleanList[c][0] < right:
                        right = min(right, bboxCleanList[c][0])

                if left > bboxList[0] - height * self.levelExtendMinimum:
                    left = bboxList[0]

                if right < bboxList[2] + height * self.levelExtendMinimum:
                    right = bboxList[2]

                if left < bboxList[0] or right > bboxList[2]:
                    bboxList = [left, bboxList[1], right, bboxList[3]]

                    detectionCleanList[a] = {"score": detectionCleanList[a]["score"], "coordinate": self._pointBuild(bboxList)}

            bboxCleanList[a] = bboxList

        return detectionCleanList

    def _crossColumnList(self, bboxList, image, cut, height, bboxOtherList):
        isCrossList = numpy.zeros(bboxList[2] - bboxList[0], bool)

        count, _, statList, _ = cv2.connectedComponentsWithStats(imageInkBuild(image[bboxList[1]:bboxList[3], bboxList[0]:bboxList[2]]), connectivity=8)

        for a in range(1, count):
            left = bboxList[0] + int(statList[a][0])
            right = left + int(statList[a][2])
            top = bboxList[1] + int(statList[a][1])
            bottom = top + int(statList[a][3])

            if min(cut - top, bottom - cut) >= height * self.levelCrossSide and (right <= bboxOtherList[0] or left >= bboxOtherList[2]):
                isCrossList[left - bboxList[0]:right - bboxList[0]] = True

        return isCrossList

    def _partBuild(self, topList, bottomList, bboxList, height):
        partList = []

        start = 0

        for a in range(1, len(topList) + 1):
            if a == len(topList) or topList[a] != topList[start] or bottomList[a] != bottomList[start]:
                if bottomList[start] > topList[start]:
                    partList.append([bboxList[0] + start, int(topList[start]), bboxList[0] + a, int(bottomList[start])])

                start = a

        if len(partList) < 2:
            return partList

        resultList = []

        for a in range(len(partList)):
            if partList[a][2] - partList[a][0] >= height:
                resultList.append(partList[a])

        return resultList

    def _cleanTrim(self, detectionCleanList, height, image):
        bboxCleanList = []

        for a in range(len(detectionCleanList)):
            bboxCleanList.append(boxFromPointList(detectionCleanList[a]["coordinate"]))

        resultList = []

        for a in range(len(detectionCleanList)):
            bboxList = bboxCleanList[a]

            if bboxList[3] - bboxList[1] < height * self.levelLineDouble:
                resultList.append(detectionCleanList[a])

                continue

            bboxPixelList = [int(value) for value in bboxList]

            topList = numpy.full(bboxPixelList[2] - bboxPixelList[0], bboxPixelList[1])
            bottomList = numpy.full(bboxPixelList[2] - bboxPixelList[0], bboxPixelList[3])

            centerY = (bboxList[1] + bboxList[3]) / 2

            isCut = False

            for b in range(len(detectionCleanList)):
                bboxOtherList = bboxCleanList[b]

                if b == a or bboxOtherList[3] - bboxOtherList[1] >= height * self.levelLineDouble or bboxOtherList[0] >= bboxList[2] or bboxOtherList[2] <= bboxList[0]:
                    continue

                if (bboxOtherList[1] + bboxOtherList[3]) / 2 > centerY and bboxOtherList[1] < bboxList[3]:
                    isCutList = ~self._crossColumnList(bboxPixelList, image, bboxOtherList[1], height, bboxOtherList)

                    bottomList[isCutList] = numpy.minimum(bottomList[isCutList], int(bboxOtherList[1]))

                    isCut = True

                if (bboxOtherList[1] + bboxOtherList[3]) / 2 < centerY and bboxOtherList[3] > bboxList[1]:
                    isCutList = ~self._crossColumnList(bboxPixelList, image, bboxOtherList[3], height, bboxOtherList)

                    topList[isCutList] = numpy.maximum(topList[isCutList], int(bboxOtherList[3]))

                    isCut = True

            if not isCut:
                resultList.append(detectionCleanList[a])

                continue

            partList = self._partBuild(topList, bottomList, bboxPixelList, height)

            for b in range(len(partList)):
                resultList.append({"score": detectionCleanList[a]["score"], "coordinate": self._pointBuild(partList[b])})

        return resultList

    def _orphanCollect(self, image, detectionDropList, bboxAcceptList):
        imageInk = imageInkBuild(image)

        resultList = []

        for a in range(len(detectionDropList)):
            bboxList = boxFromPointList(detectionDropList[a]["coordinate"])

            isReplaced = False

            for b in range(len(bboxAcceptList)):
                if self._overlapCheck(bboxList, bboxAcceptList[b]):
                    isReplaced = True

                    break

            if isReplaced:
                continue

            shape = numpy.zeros(imageInk.shape, numpy.uint8)

            cv2.fillPoly(shape, [numpy.array(detectionDropList[a]["coordinate"], numpy.int32)], 1)

            yList, xList = numpy.nonzero(imageInk & shape)

            if len(yList) == 0:
                continue

            resultList.append({"score": detectionDropList[a]["score"], "coordinate": self._pointBuild([int(xList.min()), int(yList.min()), int(xList.max()) + 1, int(yList.max()) + 1])})

        return resultList

    def _scoreFilter(self, detectionList, recognition, image):
        if len(detectionList) == 0:
            return []

        coordinateList = []

        for a in range(len(detectionList)):
            coordinateList.append(detectionList[a]["coordinate"])

        recognitionList = recognition.execute(coordinateList, image)

        resultList = []

        for a in range(len(detectionList)):
            if recognitionList[a]["score"] >= self.levelScore:
                resultList.append(detectionList[a])

        return resultList

    def detectionMerge(self, detectionList, zone, detectionCleanList, recognition, image):
        isKeepList = []
        detectionDropList = []
        bboxKeepList = []
        bboxDropList = []
        bboxList = []

        for a in range(len(detectionList)):
            bboxDetectionList = boxFromPointList(detectionList[a]["coordinate"])

            bboxList.append(bboxDetectionList)

            isKeep = not self._zoneCheck(zone, bboxDetectionList)

            isKeepList.append(isKeep)

            if isKeep:
                bboxKeepList.append(bboxDetectionList)
            else:
                detectionDropList.append(detectionList[a])
                bboxDropList.append(bboxDetectionList)

        height = self._heightBoxMedian(bboxList)

        detectionCleanList = self._cleanExtend(self._cleanTrim(self._cleanCollect(detectionCleanList, bboxKeepList, zone, bboxDropList), height, image), bboxDropList, height)

        detectionAcceptList = self._scoreFilter(detectionCleanList, recognition, image)

        bboxAcceptList = []

        for a in range(len(detectionAcceptList)):
            bboxAcceptList.append(boxFromPointList(detectionAcceptList[a]["coordinate"]))

        detectionOrphanList = self._scoreFilter(self._orphanCollect(image, detectionDropList, bboxAcceptList), recognition, image)

        return {"isKeepList": isKeepList, "detectionZoneList": sorted(detectionAcceptList + detectionOrphanList, key=lambda item: (item["coordinate"][0][1], item["coordinate"][0][0]))}

    def execute(self, bboxList, image):
        if len(bboxList) == 0:
            return {"isFound": False}

        height = self._heightBoxMedian(bboxList)

        imageGray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        levelObject = self._levelBuild(imageGray)

        sizeGrain = max(3, int(round(height * self.levelGrain)) | 1)
        sizeCore = max(3, int(round(height * self.levelCore)) | 1)

        imageGrainless = cv2.medianBlur(imageGray, sizeGrain)

        core = self._coreBuild(imageGrainless, levelObject, sizeCore, imageGray, height)

        coreGrown = self._coreGrow(imageGray, levelObject, sizeGrain, imageGrainless, core, height)

        zone = self._zoneBuild(height, coreGrown, core)

        if not zone.any():
            return {"isFound": False}

        core[zone == 0] = 0
        coreGrown[zone == 0] = 0

        imageClean = self._cleanBuild(image, core, imageGray, levelObject, zone, height, coreGrown, sizeCore)

        imageResult = image.copy()

        imageResult[zone > 0] = cv2.cvtColor(imageClean, cv2.COLOR_GRAY2BGR)[zone > 0]

        return {"isFound": True, "zone": zone, "image": imageResult}

    def __init__(self):
        self.levelBackground = 0.9
        self.levelCore = 0.3
        self.levelCoreWhite = 0.1
        self.levelZone = 0.5
        self.levelGrain = 0.15
        self.levelGrow = 1.0
        self.levelZoneSize = 3.0
        self.levelZoneStroke = 0.2
        self.levelRuleLength = 1.5
        self.levelSpeck = 0.1
        self.levelDuplicate = 0.5
        self.levelScore = 0.75
        self.levelRowHeight = 0.5
        self.levelRowOverlap = 0.7
        self.levelExtendMinimum = 0.5
        self.levelLineDouble = 1.7
        self.levelCrossSide = 0.25
