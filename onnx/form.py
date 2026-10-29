import sys
import math
import unicodedata
import cv2
import numpy

sys.dont_write_bytecode = True

# Source
import pdf
from helper import boxFromPointList, imageInkBuild, boxCenterInsideCheck

class PdfChar(pdf.Pdf):
    levelSplit = 1.5
    levelSpace = 1.0

    def _fontDecode(self, raw, font):
        resultObject = pdf.Pdf._fontDecode(self, raw, font)

        if font["byteLength"] != 2 or font["isCidResolved"] or font["isUnicodeCode"] == False:
            return resultObject

        for a in range(len(resultObject["charList"])):
            character = resultObject["charList"][a]

            if len(character) > 0 and unicodedata.east_asian_width(character[0]) in ["Na", "H"]:
                resultObject["widthFractionList"][a] = font["defaultWidthFraction"] / 2

        return resultObject

    def _showText(self, partList, font):
        charList = []

        advance = 0

        for a in range(len(partList)):
            part = partList[a]

            if part["kind"] == "string" or part["kind"] == "hexString":
                decoded = self._fontDecode(part["value"], font)

                for b in range(len(decoded["charList"])):
                    start = advance

                    if font["isVertical"]:
                        code = decoded["codeList"][b]

                        fraction = font["verticalObject"][code] if font["isCidResolved"] and code in font["verticalObject"] else font["verticalFraction"]

                        size = fraction * self.fontSize

                        advance += size + self.charSpacing
                    else:
                        size = decoded["widthFractionList"][b] * self.fontSize * self.horizontalScale

                        glyph = decoded["widthFractionList"][b] * self.fontSize + self.charSpacing

                        if font["byteLength"] == 1 and decoded["codeList"][b] == 32:
                            glyph += self.wordSpacing

                        advance += glyph * self.horizontalScale

                    charList.append({"text": decoded["charList"][b], "start": start, "end": start + size})
            elif part["kind"] == "number":
                advance -= part["value"] / 1000 * self.fontSize * (1 if font["isVertical"] else self.horizontalScale)

        renderMatrixList = self._matrixMultiply(self.ctmList, self.textMatrixList)
        deviceFontSize = self.fontSize * math.hypot(renderMatrixList[2], renderMatrixList[3])

        if self.textRender != 3 and self.textRender != 7:
            pieceList = []

            for a in range(len(charList)):
                if len(charList[a]["text"].strip()) == 0:
                    continue

                if len(pieceList) > 0 and charList[a]["start"] - pieceList[len(pieceList) - 1]["end"] <= self.fontSize * self.levelSplit:
                    pieceObject = pieceList[len(pieceList) - 1]

                    if charList[a]["start"] - pieceObject["end"] > self.fontSize * self.levelSpace:
                        pieceObject["text"] += " "

                    pieceObject["text"] += charList[a]["text"]
                    pieceObject["end"] = charList[a]["end"]
                    pieceObject["charList"].append(charList[a])

                    continue

                pieceList.append({"text": charList[a]["text"], "start": charList[a]["start"], "end": charList[a]["end"], "charList": [charList[a]]})

            for a in range(len(pieceList)):
                start = pieceList[a]["start"]
                end = pieceList[a]["end"]

                if font["isVertical"]:
                    cornerList = [
                        self._transformPoint(renderMatrixList, -self.fontSize * 0.5, self.textRise - start),
                        self._transformPoint(renderMatrixList, self.fontSize * 0.5, self.textRise - start),
                        self._transformPoint(renderMatrixList, self.fontSize * 0.5, self.textRise - end),
                        self._transformPoint(renderMatrixList, -self.fontSize * 0.5, self.textRise - end)
                    ]
                else:
                    cornerList = [
                        self._transformPoint(renderMatrixList, start, self.textRise - self.fontSize * 0.2),
                        self._transformPoint(renderMatrixList, end, self.textRise - self.fontSize * 0.2),
                        self._transformPoint(renderMatrixList, end, self.textRise + self.fontSize * 0.8),
                        self._transformPoint(renderMatrixList, start, self.textRise + self.fontSize * 0.8)
                    ]

                bboxList = boxFromPointList(cornerList)

                charBoxList = []

                for b in range(len(pieceList[a]["charList"])):
                    charObject = pieceList[a]["charList"][b]

                    if font["isVertical"]:
                        pointStart = self._transformPoint(renderMatrixList, 0, self.textRise - charObject["start"])
                        pointEnd = self._transformPoint(renderMatrixList, 0, self.textRise - charObject["end"])

                        charBoxList.append({"text": charObject["text"], "start": self.pageHeight - pointStart[1], "end": self.pageHeight - pointEnd[1]})
                    else:
                        pointStart = self._transformPoint(renderMatrixList, charObject["start"], self.textRise)
                        pointEnd = self._transformPoint(renderMatrixList, charObject["end"], self.textRise)

                        charBoxList.append({"text": charObject["text"], "start": pointStart[0], "end": pointEnd[0]})

                self.elementList.append({
                    "type": "text",
                    "charList": charBoxList,
                    "text": pieceList[a]["text"],
                    "x0": bboxList[0],
                    "y0": self.pageHeight - bboxList[3],
                    "x1": bboxList[2],
                    "y1": self.pageHeight - bboxList[1],
                    "fontSize": math.floor(deviceFontSize * 100 + 0.5) / 100,
                    "isVertical": font["isVertical"],
                    "color": self.fillColor
                })

        self.textMatrixList = self._matrixMultiply(self.textMatrixList, [1, 0, 0, 1, 0, -advance] if font["isVertical"] else [1, 0, 0, 1, advance, 0])

class Form:
    def _duplicateRemove(self, charList):
        resultList = []

        for a in range(len(charList)):
            isDuplicate = False

            for b in range(len(resultList)):
                if resultList[b]["text"] == charList[a]["text"] and self._iou(resultList[b]["bbox"], charList[a]["bbox"]) >= self.levelDuplicate:
                    isDuplicate = True

                    break

            if isDuplicate == False:
                resultList.append(charList[a])

        return resultList

    def _textMerge(self, elementList):
        resultList = []

        for a in range(len(elementList)):
            elementObject = elementList[a]

            size = elementObject["fontSize"]

            isMerged = False

            if len(resultList) > 0:
                currentObject = resultList[len(resultList) - 1]

                sizeCurrent = currentObject["fontSize"]

                if currentObject["isVertical"]:
                    gap = elementObject["y0"] - currentObject["y1"]
                    isLine = abs(elementObject["x0"] - currentObject["x0"]) <= sizeCurrent * self.levelLine
                else:
                    gap = elementObject["x0"] - currentObject["x1"]
                    isLine = abs(elementObject["y1"] - currentObject["y1"]) <= sizeCurrent * self.levelLine

                isSize = abs(size - sizeCurrent) <= max(size, sizeCurrent) * self.levelSize

                if isLine and isSize and currentObject["isVertical"] == elementObject["isVertical"] and gap >= -sizeCurrent * self.levelOverlap and gap <= sizeCurrent * self.levelGap:
                    text = currentObject["text"]
                    textNext = elementObject["text"]

                    isSpace = gap > sizeCurrent * PdfChar.levelSpace and (self._wideCheck(text[-1:] or " ") and self._wideCheck(textNext[0:1] or " ")) == False

                    currentObject["text"] = f"{text} {textNext}" if isSpace else f"{text}{textNext}"
                    currentObject["charList"] = currentObject["charList"] + elementObject["charList"]
                    currentObject["x0"] = min(currentObject["x0"], elementObject["x0"])
                    currentObject["y0"] = min(currentObject["y0"], elementObject["y0"])
                    currentObject["x1"] = max(currentObject["x1"], elementObject["x1"])
                    currentObject["y1"] = max(currentObject["y1"], elementObject["y1"])

                    isMerged = True

            if isMerged == False:
                resultList.append(dict(elementObject))

        return resultList

    def _heightBoxMedian(self, bboxList):
        sizeList = []

        for a in range(len(bboxList)):
            sizeList.append(min(bboxList[a][2] - bboxList[a][0], bboxList[a][3] - bboxList[a][1]))

        sizeList.sort()

        return sizeList[int(len(sizeList) / 2)] if len(sizeList) > 0 else 1

    def _runList(self, profileList, isEmptyList):
        resultList = []

        start = -1

        for a in range(len(profileList) + 1):
            isEmpty = a < len(profileList) and isEmptyList[a]

            if isEmpty and start < 0:
                start = a
            elif isEmpty == False and start >= 0:
                resultList.append([start, a])

                start = -1

        return resultList

    def _boxSplit(self, bboxList, imageInk, isVertical, height):
        x1 = max(0, int(bboxList[0]))
        y1 = max(0, int(bboxList[1]))
        x2 = min(imageInk.shape[1], int(math.ceil(bboxList[2])))
        y2 = min(imageInk.shape[0], int(math.ceil(bboxList[3])))

        crop = imageInk[y1:y2, x1:x2]

        if crop.size == 0:
            return []

        if isVertical:
            crop = crop.transpose()

        thickness = crop.shape[0]

        profileList = crop.sum(axis=0)

        isLineList = []
        isEmptyList = []

        for a in range(len(profileList)):
            isLineList.append(profileList[a] >= thickness * self.levelLineCover)
            isEmptyList.append(profileList[a] <= thickness * self.levelEmpty)

        lineRunList = []

        lineCandidateList = self._runList(profileList, isLineList)

        for a in range(len(lineCandidateList)):
            if self._lineExtendCheck(imageInk, lineCandidateList[a], [x1, y1, x2, y2], isVertical, height):
                lineRunList.append(lineCandidateList[a])

        for a in range(len(lineRunList)):
            if lineRunList[a][1] - lineRunList[a][0] <= thickness * self.levelLineWidth:
                for b in range(lineRunList[a][0], lineRunList[a][1]):
                    isEmptyList[b] = True

        inkRunList = self._runList(profileList, [value == False for value in isEmptyList])

        segmentList = []

        for a in range(len(inkRunList)):
            if len(segmentList) > 0:
                gapStart = segmentList[len(segmentList) - 1][1]
                gapEnd = inkRunList[a][0]

                if gapEnd - gapStart < height * self.levelSplitGap and self._lineInside(lineRunList, gapStart, gapEnd, thickness) == False:
                    segmentList[len(segmentList) - 1][1] = inkRunList[a][1]

                    continue

            segmentList.append(list(inkRunList[a]))

        resultList = []

        for a in range(len(segmentList)):
            if segmentList[a][1] - segmentList[a][0] < 1:
                continue

            cropSegment = crop[:, segmentList[a][0]:segmentList[a][1]]

            rowProfileList = cropSegment.sum(axis=1)

            isInkList = []

            for b in range(len(rowProfileList)):
                isInkList.append(rowProfileList[b] > 0 and rowProfileList[b] < cropSegment.shape[1] * self.levelLineCover)

            rowRunList = self._runList(rowProfileList, isInkList)

            if len(rowRunList) == 0:
                continue

            runBest = None
            inkBest = -1

            for b in range(len(rowRunList)):
                ink = int(rowProfileList[rowRunList[b][0]:rowRunList[b][1]].sum())

                if ink > inkBest:
                    inkBest = ink
                    runBest = rowRunList[b]

            crossStart = runBest[0]
            crossEnd = runBest[1]

            for b in range(len(rowRunList)):
                if rowRunList[b] is runBest:
                    continue

                if rowRunList[b][1] <= crossStart and crossStart - rowRunList[b][1] <= height * self.levelTrimGap:
                    crossStart = rowRunList[b][0]
                elif rowRunList[b][0] >= crossEnd and rowRunList[b][0] - crossEnd <= height * self.levelTrimGap:
                    crossEnd = rowRunList[b][1]

            if isVertical:
                resultList.append({"bbox": [x1 + crossStart, y1 + segmentList[a][0], x1 + crossEnd, y1 + segmentList[a][1]], "bboxRecognize": [bboxList[0], y1 + segmentList[a][0], bboxList[2], y1 + segmentList[a][1]]})
            else:
                resultList.append({"bbox": [x1 + segmentList[a][0], y1 + crossStart, x1 + segmentList[a][1], y1 + crossEnd], "bboxRecognize": [x1 + segmentList[a][0], bboxList[1], x1 + segmentList[a][1], bboxList[3]]})

        return resultList

    def _lineSplit(self, bboxList, imageInk, height):
        if bboxList[3] - bboxList[1] < height * self.levelLineDouble:
            return [bboxList]

        x1 = max(0, int(bboxList[0]))
        y1 = max(0, int(bboxList[1]))
        x2 = min(imageInk.shape[1], int(math.ceil(bboxList[2])))
        y2 = min(imageInk.shape[0], int(math.ceil(bboxList[3])))

        profileList = imageInk[y1:y2, x1:x2].sum(axis=1)

        inkList = []

        for a in range(len(profileList)):
            if profileList[a] > 0:
                inkList.append(a)

        if len(inkList) == 0:
            return [bboxList]

        top = inkList[0]
        bottom = inkList[len(inkList) - 1]

        valueList = sorted(profileList[top:bottom + 1])

        median = valueList[int(len(valueList) / 2)]

        start = top + int((bottom - top) * self.levelLineMiddle)
        end = bottom - int((bottom - top) * self.levelLineMiddle)

        indexMinimum = -1

        for a in range(start, end + 1):
            if indexMinimum < 0 or profileList[a] < profileList[indexMinimum]:
                indexMinimum = a

        if indexMinimum < 0 or profileList[indexMinimum] > median * self.levelLineValley:
            return [bboxList]

        return [[bboxList[0], bboxList[1], bboxList[2], y1 + indexMinimum], [bboxList[0], y1 + indexMinimum, bboxList[2], bboxList[3]]]

    def _lineExtendCheck(self, imageInk, run, bboxList, isVertical, height):
        extend = int(math.ceil(height * self.levelLineExtend))

        if isVertical:
            band = imageInk[bboxList[1] + run[0]:bboxList[1] + run[1], :].transpose()
            start = bboxList[0]
            end = bboxList[2]
        else:
            band = imageInk[:, bboxList[0] + run[0]:bboxList[0] + run[1]]
            start = bboxList[1]
            end = bboxList[3]

        beforeList = band[max(0, start - extend):start]
        afterList = band[end:end + extend]

        if len(beforeList) < extend or len(afterList) < extend:
            return False

        return beforeList.max(axis=1).sum() >= extend * self.levelLineCover and afterList.max(axis=1).sum() >= extend * self.levelLineCover

    def _lineInside(self, lineRunList, start, end, thickness):
        for a in range(len(lineRunList)):
            if lineRunList[a][0] >= start and lineRunList[a][1] <= end and lineRunList[a][1] - lineRunList[a][0] <= thickness * self.levelLineWidth:
                return True

        return False

    def _lineCollect(self, image, height):
        imageInk = cv2.adaptiveThreshold(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, int(height) * 2 + 1, self.levelRuleContrast)

        length = max(1, int(round(height * self.levelRuleLength)))

        imageVertical = cv2.morphologyEx(imageInk, cv2.MORPH_OPEN, numpy.ones((length, 1), numpy.uint8))
        imageHorizontal = cv2.morphologyEx(imageInk, cv2.MORPH_OPEN, numpy.ones((1, length), numpy.uint8))

        resultObject = {"verticalList": [], "horizontalList": []}

        count, _, statList, _ = cv2.connectedComponentsWithStats(imageVertical)

        for a in range(1, count):
            x, y, width, heightLine = statList[a][0:4]

            if width <= height * self.levelRuleThick or heightLine >= width * self.levelRuleAspect:
                resultObject["verticalList"].append([int(x), int(y), int(x + width), int(y + heightLine)])

        count, _, statList, _ = cv2.connectedComponentsWithStats(imageHorizontal)

        for a in range(1, count):
            x, y, width, heightLine = statList[a][0:4]

            if heightLine <= height * self.levelRuleThick or width >= heightLine * self.levelRuleAspect:
                resultObject["horizontalList"].append([int(x), int(y), int(x + width), int(y + heightLine)])

        resultObject["dashList"] = self._dashCollect(height, imageInk, resultObject["horizontalList"])

        return resultObject

    def _uniformCheck(self, valueList, median):
        count = 0

        for a in range(len(valueList)):
            if valueList[a] >= median / 2 and valueList[a] <= median * 2:
                count += 1

        return count >= len(valueList) * self.levelDashUniform

    def _ruleEndCheck(self, horizontalList, end, start, y, reach):
        for a in range(len(horizontalList)):
            bboxLineList = horizontalList[a]

            if bboxLineList[0] <= end and bboxLineList[2] >= start and abs((bboxLineList[1] + bboxLineList[3]) / 2 - y) <= reach:
                return True

        return False

    def _dashCollect(self, height, imageInk, horizontalList):
        thickness = max(1, int(round(height * self.levelRuleThick)))
        gap = max(1, int(round(height * self.levelDashGap)))
        length = max(1, int(round(height * self.levelRuleLength)))

        imageWide = cv2.morphologyEx(imageInk, cv2.MORPH_OPEN, numpy.ones((1, thickness + 1), numpy.uint8))
        imageThin = imageInk - imageWide
        imageClose = cv2.morphologyEx(imageThin, cv2.MORPH_CLOSE, numpy.ones((gap, 1), numpy.uint8))
        imageCandidate = cv2.morphologyEx(imageClose, cv2.MORPH_OPEN, numpy.ones((length, 1), numpy.uint8))

        count, _, statList, _ = cv2.connectedComponentsWithStats(imageCandidate)

        candidateList = []

        for a in range(1, count):
            x, y, width, heightLine = [int(value) for value in statList[a][0:4]]

            if width > thickness:
                continue

            profileList = imageThin[y:y + heightLine, x:x + width].max(axis=1)

            runList = self._runList(profileList, [value > 0 for value in profileList])

            if len(runList) < self.countDash or profileList.sum() >= heightLine * self.levelLineCover:
                continue

            lengthList = []
            gapList = []

            for b in range(len(runList)):
                lengthList.append(runList[b][1] - runList[b][0])

                if b > 0:
                    gapList.append(runList[b][0] - runList[b - 1][1])

            lengthMedian = sorted(lengthList)[int(len(lengthList) / 2)]
            gapMedian = sorted(gapList)[int(len(gapList) / 2)]

            if lengthMedian < height * self.levelDashMinimum or lengthMedian > height * self.levelDashMaximum or gapMedian < height * self.levelDashMinimum:
                continue

            if self._uniformCheck(lengthList, lengthMedian) == False or self._uniformCheck(gapList, gapMedian) == False:
                continue

            countIsolated = 0

            for b in range(len(runList)):
                inkLeft = imageInk[y + runList[b][0]:y + runList[b][1], x - 1].sum() if x > 0 else 0
                inkRight = imageInk[y + runList[b][0]:y + runList[b][1], min(imageInk.shape[1] - 1, x + width)].sum()

                if inkLeft <= lengthList[b] * self.levelDashSide and inkRight <= lengthList[b] * self.levelDashSide:
                    countIsolated += 1

            if countIsolated < len(runList) * self.levelDashIsolated:
                continue

            if self._ruleEndCheck(horizontalList, x + width, x, y, gap) == False or self._ruleEndCheck(horizontalList, x + width, x, y + heightLine, gap) == False:
                continue

            candidateList.append({"bbox": [x, y, x + width, y + heightLine], "period": lengthMedian + gapMedian})

        resultList = []

        for a in range(len(candidateList)):
            bboxList = candidateList[a]["bbox"]

            period = candidateList[a]["period"]

            for b in range(len(candidateList)):
                bboxOtherList = candidateList[b]["bbox"]

                if b != a and abs(candidateList[b]["period"] - period) <= period * self.levelDashPeriod and self._overlap(bboxList[1], bboxList[3], bboxOtherList[1], bboxOtherList[3]) >= min(bboxList[3] - bboxList[1], bboxOtherList[3] - bboxOtherList[1]) * self.levelDashPartner:
                    resultList.append(bboxList)

                    break

        return resultList

    def _dashErase(self, image, dashList):
        imageClean = image.copy()

        for a in range(len(dashList)):
            bboxList = dashList[a]

            imageClean[bboxList[1]:bboxList[3], max(0, bboxList[0] - 1):bboxList[2] + 1] = 255

        return imageClean

    def _bandFind(self, bboxList, horizontalList):
        centerX = (bboxList[0] + bboxList[2]) / 2
        centerY = (bboxList[1] + bboxList[3]) / 2

        top = None
        bottom = None

        for a in range(len(horizontalList)):
            bboxLineList = horizontalList[a]

            if bboxLineList[0] > centerX or bboxLineList[2] < centerX:
                continue

            if bboxLineList[3] <= bboxList[1] and (top == None or bboxLineList[3] > top):
                top = bboxLineList[3]

            if bboxLineList[1] >= bboxList[3] and (bottom == None or bboxLineList[1] < bottom):
                bottom = bboxLineList[1]

        if top == None or bottom == None:
            return None

        return [top, bottom]

    def _rowLeftFind(self, anchorObject, itemList, height):
        bboxAnchorList = anchorObject["bbox"]

        resultObject = None

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            if itemList[a]["type"] != "row" or bboxList[2] > bboxAnchorList[0] + height * self.levelMargin or self._rangeCheck(bboxList, bboxAnchorList) == False:
                continue

            if resultObject == None or bboxList[2] > resultObject["bbox"][2]:
                resultObject = itemList[a]

        return resultObject

    def _rowBandBuild(self, rowObject, itemList):
        bboxRowList = rowObject["bbox"]

        above = None
        below = None

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            if itemList[a]["type"] != "row" or itemList[a] is rowObject or self._overlap(bboxList[0], bboxList[2], bboxRowList[0], bboxRowList[2]) <= 0:
                continue

            if bboxList[3] <= bboxRowList[1] and (above == None or bboxList[3] > above):
                above = bboxList[3]

            if bboxList[1] >= bboxRowList[3] and (below == None or bboxList[1] < below):
                below = bboxList[1]

        if above == None and below == None:
            return None

        top = (above + bboxRowList[1]) / 2 if above != None else bboxRowList[1] - (below - bboxRowList[3]) / 2
        bottom = (below + bboxRowList[3]) / 2 if below != None else bboxRowList[3] + (bboxRowList[1] - above) / 2

        return [top, bottom]

    def _rowVirtualCheck(self, anchorObject, itemList, height, itemObject):
        rowObject = anchorObject if anchorObject["type"] == "row" else self._rowLeftFind(anchorObject, itemList, height)

        if rowObject == None:
            return False

        bandList = self._rowBandBuild(rowObject, itemList)

        bboxList = itemObject["bbox"]

        centerY = (bboxList[1] + bboxList[3]) / 2

        if bandList == None or centerY < bandList[0] or centerY > bandList[1] or itemObject["type"] == "row" or bboxList[2] > rowObject["bbox"][0] + height * self.levelMargin:
            return False

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            if itemList[a] is itemObject or itemList[a] is rowObject or itemList[a] is anchorObject:
                continue

            centerX = (bboxOtherList[0] + bboxOtherList[2]) / 2

            if centerX <= bboxList[2] or centerX >= rowObject["bbox"][0]:
                continue

            if self._rangeCheck(bboxOtherList, bboxList):
                return False

            if itemList[a]["type"] == "row":
                bandOtherList = self._rowBandBuild(itemList[a], itemList)

                if bandOtherList != None and centerY >= bandOtherList[0] and centerY <= bandOtherList[1]:
                    return False

        return True

    def _sameRowCheck(self, itemObject, anchorObject, itemList, lineObject, height):
        bboxList = itemObject["bbox"]
        bboxAnchorList = anchorObject["bbox"]

        if self._rangeCheck(bboxList, bboxAnchorList):
            return True

        bandList = self._bandFind(bboxList, lineObject["horizontalList"])
        bandAnchorList = self._bandFind(bboxAnchorList, lineObject["horizontalList"])

        if bandAnchorList == None:
            return self._rowVirtualCheck(anchorObject, itemList, height, itemObject)

        if bandList == None:
            return False

        if abs(bandList[0] - bandAnchorList[0]) > height * self.levelMargin or abs(bandList[1] - bandAnchorList[1]) > height * self.levelMargin:
            return False

        bboxSpanList = [0, min(bboxList[1], bboxAnchorList[1]), 0, max(bboxList[3], bboxAnchorList[3])]

        if self._wallCheck(lineObject["verticalList"], bboxList[2] - height * self.levelMargin, bboxAnchorList[0] + height * self.levelMargin, bboxSpanList) == False:
            return False

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            if itemList[a] is itemObject or itemList[a] is anchorObject:
                continue

            centerX = (bboxOtherList[0] + bboxOtherList[2]) / 2

            if centerX > bboxList[2] and centerX < bboxAnchorList[0] and self._rangeCheck(bboxOtherList, bboxList):
                return False

        return True

    def _wallCount(self, lineList, start, end, bboxList):
        count = 0

        for a in range(len(lineList)):
            bboxLineList = lineList[a]

            if bboxLineList[2] <= start or bboxLineList[0] >= end:
                continue

            if self._overlap(bboxLineList[1], bboxLineList[3], bboxList[1], bboxList[3]) >= (bboxList[3] - bboxList[1]) * self.levelLineCover:
                count += 1

        return count

    def _wallCheck(self, lineList, start, end, bboxList):
        for a in range(len(lineList)):
            bboxLineList = lineList[a]

            if bboxLineList[2] <= start or bboxLineList[0] >= end:
                continue

            if self._overlap(bboxLineList[1], bboxLineList[3], bboxList[1], bboxList[3]) >= (bboxList[3] - bboxList[1]) * self.levelLineCover:
                return True

        return False

    def _lineNearCheck(self, lineList, start, end, bboxList, height):
        for a in range(len(lineList)):
            bboxLineList = lineList[a]

            if bboxLineList[2] <= start or bboxLineList[0] >= end:
                continue

            if self._overlap(bboxLineList[1], bboxLineList[3], bboxList[1] - height * self.levelLineReach, bboxList[3] + height * self.levelLineReach) > 0:
                return True

        return False

    def _cellJoin(self, runList):
        textList = []
        charList = []

        bboxList = list(runList[0]["bbox"])

        for a in range(len(runList)):
            text = runList[a]["text"].strip()

            if a > 0:
                textPrevious = textList[len(textList) - 1]

                gap = runList[a]["bbox"][0] - runList[a - 1]["bbox"][2]

                isSpace = gap > (bboxList[3] - bboxList[1]) * PdfChar.levelSpace and (self._wideCheck(textPrevious[-1:] or " ") and self._wideCheck(text[0:1] or " ")) == False

                if isSpace:
                    textList.append(" ")

            textList.append(text)

            charList = charList + self._charPosition(runList[a])

            bboxList = [min(bboxList[0], runList[a]["bbox"][0]), min(bboxList[1], runList[a]["bbox"][1]), max(bboxList[2], runList[a]["bbox"][2]), max(bboxList[3], runList[a]["bbox"][3])]

        return {"text": "".join(textList), "bbox": bboxList, "isVertical": False, "charList": charList, "page": runList[0].get("page", 1)}

    def _bareNumberCheck(self, text):
        return len(text) > 0 and unicodedata.category(text[0]) != "Ps" and self._numberCheck(text)

    def _letterContain(self, text):
        for a in range(len(text)):
            if unicodedata.category(text[a])[0] == "L":
                return True

        return False

    def _numberJoinCheck(self, runList, index):
        if index == 0 or index == len(runList) - 1:
            return False

        isLetter = False

        for a in [index - 1, index + 1]:
            text = self._textClean(runList[a]["text"])

            if self._bareNumberCheck(text):
                return False

            if self._letterContain(text):
                isLetter = True

        if isLetter == False:
            return False

        for a in [index, index + 1]:
            heightLocal = min(runList[a - 1]["bbox"][3] - runList[a - 1]["bbox"][1], runList[a]["bbox"][3] - runList[a]["bbox"][1])

            if runList[a]["bbox"][0] - runList[a - 1]["bbox"][2] < heightLocal * self.levelLetterSpace:
                return False

        return True

    def _alignFind(self, itemList, itemObject, lineObject, height):
        horizontalList = lineObject["horizontalList"]

        bboxList = itemObject["bbox"]

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            if itemList[a] is itemObject or self._rangeCheck(bboxOtherList, bboxList):
                continue

            if abs((bboxOtherList[1] + bboxOtherList[3]) / 2 - (bboxList[1] + bboxList[3]) / 2) > height * self.levelGutterReach:
                continue

            if abs(bboxOtherList[0] - bboxList[0]) > height * self.levelGutterAlign:
                continue

            if bboxOtherList[1] < bboxList[1] and self._ruleBetweenCheck(horizontalList, bboxOtherList, bboxList):
                continue

            if bboxOtherList[1] > bboxList[1] and self._ruleBetweenCheck(horizontalList, bboxList, bboxOtherList):
                continue

            for b in range(len(itemList)):
                bboxLeftList = itemList[b]["bbox"]

                if b != a and bboxLeftList[2] <= bboxOtherList[0] + height * self.levelMargin and self._rangeCheck(bboxLeftList, bboxOtherList) and self._wallCheck(lineObject["verticalList"], bboxLeftList[2] - height * self.levelMargin, bboxOtherList[0] + height * self.levelMargin, bboxOtherList) == False:
                    return itemList[a]

        return None

    def _gutterCheck(self, itemList, runList, index, lineObject, height):
        alignObject = self._alignFind(itemList, runList[index], lineObject, height)

        if alignObject == None:
            return False

        if index == len(runList) - 1 and len(self._textClean(runList[index]["text"])) == 1:
            isLastAlign = True

            for a in range(len(itemList)):
                bboxList = itemList[a]["bbox"]

                if itemList[a] is alignObject or bboxList[0] < alignObject["bbox"][2] - height * self.levelMargin or self._rangeCheck(bboxList, alignObject["bbox"]) == False:
                    continue

                if self._wallCheck(lineObject["verticalList"], alignObject["bbox"][2] - height * self.levelMargin, bboxList[0] + height * self.levelMargin, alignObject["bbox"]) == False:
                    isLastAlign = False

            if isLastAlign:
                return False

        countAlign = 0

        for a in range(1, len(runList)):
            if self._alignFind(itemList, runList[a], lineObject, height) != None:
                countAlign += 1

        return countAlign < 2

    def _cellRunSplit(self, runList, itemList, lineObject, height):
        if len(runList) < 2:
            return [runList]

        gapList = []

        for a in range(1, len(runList)):
            gapList.append(runList[a]["bbox"][0] - runList[a - 1]["bbox"][2])

        gapSortedList = sorted(gapList)

        gapMedian = gapSortedList[int((len(gapSortedList) - 1) / 2)]

        isLetter = True

        for a in range(len(runList)):
            if self._letterCheck(runList[a]) == False:
                isLetter = False

        resultList = [[runList[0]]]

        for a in range(1, len(runList)):
            gap = gapList[a - 1]

            heightLocal = min(runList[a - 1]["bbox"][3] - runList[a - 1]["bbox"][1], runList[a]["bbox"][3] - runList[a]["bbox"][1])

            isJoin = gap <= heightLocal * self.levelGap

            if isJoin == False and len(runList) >= 3 and (self._letterCheck(runList[a - 1]) or self._letterCheck(runList[a]) or gap <= heightLocal * self.levelPitchRatio):
                isJoin = gap <= gapMedian * self.levelPitchRatio

            if isJoin == False and len(runList) == 2:
                isJoin = isLetter

            for b in [a - 1, a]:
                if isJoin and self._bareNumberCheck(self._textClean(runList[b]["text"])) and self._numberJoinCheck(runList, b) == False:
                    isJoin = False

            if isJoin and self._gutterCheck(itemList, runList, a, lineObject, height):
                isJoin = False

            if isJoin:
                resultList[len(resultList) - 1].append(runList[a])
            else:
                resultList.append([runList[a]])

        return resultList

    def _letterSpaceCheck(self, runList):
        if len(runList) < self.countLetterSpace:
            return False

        gapList = []

        for a in range(len(runList)):
            if self._letterCheck(runList[a]) == False:
                return False

            if a > 0:
                gapList.append(runList[a]["bbox"][0] - runList[a - 1]["bbox"][2])

        return max(gapList) <= max(min(gapList), 0) * self.levelPitchRatio + (runList[0]["bbox"][3] - runList[0]["bbox"][1]) * self.levelMargin

    def _cellMerge(self, itemList, lineObject, height):
        lineList = lineObject["verticalList"]

        candidateList = []

        for a in range(len(itemList)):
            itemObject = itemList[a]

            if itemObject.get("isOption") or len(self._textClean(itemObject["text"])) == 0:
                continue

            candidateList.append(itemObject)

        candidateList.sort(key=lambda itemObject: itemObject["bbox"][0])

        chainList = []

        for a in range(len(candidateList)):
            itemObject = candidateList[a]

            bboxList = itemObject["bbox"]

            chainBest = None
            gapBest = -1

            for b in range(len(chainList)):
                lastObject = chainList[b][len(chainList[b]) - 1]

                bboxLastList = lastObject["bbox"]

                gap = bboxList[0] - bboxLastList[2]

                if gap < -height * self.levelMargin or self._rangeCheck(bboxList, bboxLastList) == False:
                    continue

                if gapBest < 0 or gap < gapBest:
                    gapBest = gap
                    chainBest = chainList[b]

            isSize = False

            if chainBest != None:
                bboxLastList = chainBest[len(chainBest) - 1]["bbox"]

                heightItem = bboxList[3] - bboxList[1]
                heightLast = bboxLastList[3] - bboxLastList[1]

                isSize = abs(heightItem - heightLast) <= max(heightItem, heightLast) * self.levelCellSize

            if isSize:
                chainBest.append(itemObject)
            else:
                chainList.append([itemObject])

        removeList = []
        addList = []

        for a in range(len(chainList)):
            chain = chainList[a]

            runList = [[chain[0]]]

            for b in range(1, len(chain)):
                bboxPreviousList = chain[b - 1]["bbox"]
                bboxList = chain[b]["bbox"]

                bboxLineList = [0, max(bboxPreviousList[1], bboxList[1]), 0, min(bboxPreviousList[3], bboxList[3])]

                if self._wallCheck(lineList, bboxPreviousList[2] - height * self.levelMargin, bboxList[0] + height * self.levelMargin, bboxLineList):
                    runList.append([chain[b]])
                else:
                    runList[len(runList) - 1].append(chain[b])

            for b in range(len(runList)):
                run = runList[b]

                if len(run) < 2:
                    continue

                bboxFirstList = run[0]["bbox"]
                bboxLastList = run[len(run) - 1]["bbox"]

                isCell = self._wallCheck(lineList, -1, bboxFirstList[0] + height * self.levelMargin, bboxFirstList) and self._wallCheck(lineList, bboxLastList[2] - height * self.levelMargin, math.inf, bboxLastList)

                isColumn = True

                for c in range(1, len(run)):
                    bboxPreviousList = run[c - 1]["bbox"]
                    bboxList = run[c]["bbox"]

                    if self._lineNearCheck(lineList, bboxPreviousList[2], bboxList[0], [0, min(bboxPreviousList[1], bboxList[1]), 0, max(bboxPreviousList[3], bboxList[3])], height) == False:
                        isColumn = False

                        break

                if isColumn:
                    continue

                groupList = self._cellRunSplit(run, candidateList, lineObject, height)

                for c in range(len(groupList)):
                    if len(groupList[c]) < 2:
                        continue

                    if isCell == False and self._letterSpaceCheck(groupList[c]) == False:
                        continue

                    for d in range(len(groupList[c])):
                        removeList.append(groupList[c][d])

                    addList.append(self._cellJoin(groupList[c]))

        resultList = []

        for a in range(len(itemList)):
            if itemList[a] not in removeList:
                resultList.append(itemList[a])

        return resultList + addList

    def _ellipseSpread(self, contour):
        (centerX, centerY), (axisFirst, axisSecond), angle = cv2.fitEllipse(contour)

        radian = math.radians(angle)

        distanceXList = contour[:, 0, 0] - centerX
        distanceYList = contour[:, 0, 1] - centerY

        firstList = distanceXList * math.cos(radian) + distanceYList * math.sin(radian)
        secondList = distanceYList * math.cos(radian) - distanceXList * math.sin(radian)

        return float(numpy.std(numpy.sqrt((firstList / (axisFirst / 2)) ** 2 + (secondList / (axisSecond / 2)) ** 2)))

    def _ringCollect(self, image, height):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        sizeBlock = int(height * self.levelRingBlock) * 2 + 1

        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, sizeBlock, self.levelRingContrast)

        contourList, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)

        ringList = []

        for a in range(len(contourList)):
            if hierarchy[0][a][3] >= 0:
                continue

            x, y, width, heightContour = cv2.boundingRect(contourList[a])

            if width < height * self.levelRingSizeMinimum or width > height * self.levelRingSizeMaximum or heightContour < height * self.levelRingSizeMinimum or heightContour > height * self.levelRingSizeMaximum:
                continue

            area = cv2.contourArea(contourList[a])

            areaHole = 0

            child = hierarchy[0][a][2]

            while child >= 0:
                areaHole = max(areaHole, cv2.contourArea(contourList[child]))

                child = hierarchy[0][child][0]

            if area <= 0 or areaHole < area * self.levelRingHole:
                continue

            if self._ellipseSpread(contourList[a]) > self.levelRingSpread:
                continue

            (centerX, centerY), radius = cv2.minEnclosingCircle(contourList[a])

            ringList.append({"bbox": [float(centerX - radius), float(centerY - radius), float(centerX + radius), float(centerY + radius)]})

        return ringList

    def _ringInterior(self, itemList, ringList, image, imageInk, recognition):
        resultList = []

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            ringObject = None

            for b in range(len(ringList)):
                if self._iou(bboxList, ringList[b]["bbox"]) >= self.levelRingArtifact:
                    ringObject = ringList[b]

                    break

            if ringObject == None:
                resultList.append(itemList[a])

                continue

            bboxRingList = ringObject["bbox"]

            centerX = (bboxRingList[0] + bboxRingList[2]) / 2
            centerY = (bboxRingList[1] + bboxRingList[3]) / 2

            radius = (bboxRingList[2] - bboxRingList[0]) / 2 * self.levelRingInner

            x1 = int(centerX - radius)
            y1 = int(centerY - radius)
            x2 = int(centerX + radius)
            y2 = int(centerY + radius)

            if imageInk[y1:y2, x1:x2].sum() == 0:
                continue

            recognitionList = recognition.execute([[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]], image)

            text = recognitionList[0]["text"].strip()

            if len(text) == 0:
                continue

            itemObject = dict(itemList[a])

            itemObject["text"] = text
            itemObject["bbox"] = [x1, y1, x2, y2]

            resultList.append(itemObject)

        for a in range(len(ringList)):
            bboxRingList = ringList[a]["bbox"]

            centerX = (bboxRingList[0] + bboxRingList[2]) / 2
            centerY = (bboxRingList[1] + bboxRingList[3]) / 2

            isCovered = False

            for b in range(len(resultList)):
                bboxList = resultList[b]["bbox"]

                if bboxList[0] <= centerX and bboxList[2] >= centerX and bboxList[1] <= centerY and bboxList[3] >= centerY:
                    isCovered = True

                    break

            if isCovered:
                continue

            radius = (bboxRingList[2] - bboxRingList[0]) / 2 * self.levelRingInner

            x1 = int(centerX - radius)
            y1 = int(centerY - radius)
            x2 = int(centerX + radius)
            y2 = int(centerY + radius)

            if imageInk[y1:y2, x1:x2].sum() == 0:
                continue

            recognitionList = recognition.execute([[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]], image)

            text = recognitionList[0]["text"].strip()

            if len(text) > 0:
                resultList.append({"text": text, "bbox": [x1, y1, x2, y2], "isVertical": False, "charList": [], "page": 1})

        return resultList

    def _verticalCandidateCheck(self, itemObject):
        text = itemObject["text"].strip()

        if len(text) == 0 or self._digitCheck(text) or itemObject.get("isOption"):
            return False

        bboxList = itemObject["bbox"]

        return len(text) == 1 or bboxList[2] - bboxList[0] < bboxList[3] - bboxList[1]

    def _digitCheck(self, text):
        for a in range(len(text)):
            if text[a] not in "0123456789０１２３４５６７８９":
                return False

        return True

    def _ruleBetweenCheck(self, horizontalList, bboxUpperList, bboxLowerList):
        centerX = (bboxUpperList[0] + bboxUpperList[2] + bboxLowerList[0] + bboxLowerList[2]) / 4

        for a in range(len(horizontalList)):
            bboxLineList = horizontalList[a]

            if bboxLineList[0] <= centerX and bboxLineList[2] >= centerX and bboxLineList[1] >= (bboxUpperList[1] + bboxUpperList[3]) / 2 and bboxLineList[3] <= (bboxLowerList[1] + bboxLowerList[3]) / 2:
                return True

        return False

    def _betweenCheck(self, itemList, bboxUpperList, bboxLowerList):
        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            if centerY > bboxUpperList[3] and centerY < bboxLowerList[1] and centerX > min(bboxUpperList[0], bboxLowerList[0]) and centerX < max(bboxUpperList[2], bboxLowerList[2]):
                return True

        return False

    def _verticalMerge(self, itemList, horizontalList):
        candidateList = []
        otherList = []

        for a in range(len(itemList)):
            if self._verticalCandidateCheck(itemList[a]):
                candidateList.append(itemList[a])
            else:
                otherList.append(itemList[a])

        candidateList.sort(key=lambda itemObject: itemObject["bbox"][1])

        columnList = []

        for a in range(len(candidateList)):
            bboxList = candidateList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            height = bboxList[3] - bboxList[1]

            isAdded = False

            for b in range(len(columnList)):
                lastBboxList = columnList[b][len(columnList[b]) - 1]["bbox"]

                lastCenterX = (lastBboxList[0] + lastBboxList[2]) / 2
                lastWidth = lastBboxList[2] - lastBboxList[0]

                if abs(centerX - lastCenterX) > max(lastWidth, bboxList[2] - bboxList[0]) / 2:
                    continue

                if bboxList[1] - lastBboxList[3] > height * self.levelVerticalGap:
                    continue

                if self._ruleBetweenCheck(horizontalList, lastBboxList, bboxList):
                    continue

                if self._betweenCheck(candidateList, lastBboxList, bboxList):
                    continue

                lastHeight = lastBboxList[3] - lastBboxList[1]

                if abs(height - lastHeight) > max(height, lastHeight) * self.levelVerticalSize:
                    continue

                columnList[b].append(candidateList[a])

                isAdded = True

                break

            if isAdded == False:
                columnList.append([candidateList[a]])

        columnSplitList = []

        for a in range(len(columnList)):
            columnSplitList = columnSplitList + self._pitchSplit(columnList[a])

        columnList = columnSplitList

        verticalList = []

        for a in range(len(columnList)):
            if len(columnList[a]) < self.countVerticalMinimum:
                for b in range(len(columnList[a])):
                    otherList.append(columnList[a][b])

                continue

            text = ""
            bboxList = list(columnList[a][0]["bbox"])

            for b in range(len(columnList[a])):
                text += columnList[a][b]["text"].strip()

                bboxList = self._bboxExpand(bboxList, columnList[a][b]["bbox"])

            verticalList.append({"text": text, "bbox": bboxList})

        return {"verticalList": verticalList, "itemList": otherList}

    def _pitchSplit(self, charList):
        if len(charList) < 2:
            return [charList]

        gapList = []
        heightList = []

        for a in range(len(charList) - 1):
            gapList.append(charList[a + 1]["bbox"][1] - charList[a]["bbox"][3])

        for a in range(len(charList)):
            heightList.append(charList[a]["bbox"][3] - charList[a]["bbox"][1])

        height = sorted(heightList)[int(len(heightList) / 2)]

        gapMedian = sorted(gapList)[int(len(gapList) / 2)]

        indexOutlier = -1

        for a in range(len(gapList)):
            if gapList[a] > max(gapMedian * self.levelGapOutlier, height) and (indexOutlier < 0 or gapList[a] > gapList[indexOutlier]):
                indexOutlier = a

        if indexOutlier >= 0:
            return self._pitchSplit(charList[0:indexOutlier + 1]) + self._pitchSplit(charList[indexOutlier + 1:])

        indexBest = -1
        varianceBest = -1

        if len(charList) < self.countVerticalMinimum * 2:
            return [charList]

        for a in range(self.countVerticalMinimum - 1, len(gapList) - self.countVerticalMinimum + 1):
            firstList = gapList[0:a]
            secondList = gapList[a + 1:]

            meanFirst = sum(firstList) / len(firstList)
            meanSecond = sum(secondList) / len(secondList)

            if abs(meanFirst - meanSecond) <= height * self.levelPitch or max(meanFirst, meanSecond) < min(meanFirst, meanSecond) * self.levelPitchRatio:
                continue

            variance = 0

            for b in range(len(firstList)):
                variance += (firstList[b] - meanFirst) ** 2

            for b in range(len(secondList)):
                variance += (secondList[b] - meanSecond) ** 2

            if varianceBest < 0 or variance < varianceBest:
                varianceBest = variance
                indexBest = a

        if indexBest < 0:
            return [charList]

        return self._pitchSplit(charList[0:indexBest + 1]) + self._pitchSplit(charList[indexBest + 1:])

    def _bboxExpand(self, bboxList, bboxOtherList):
        return [
            min(bboxList[0], bboxOtherList[0]),
            min(bboxList[1], bboxOtherList[1]),
            max(bboxList[2], bboxOtherList[2]),
            max(bboxList[3], bboxOtherList[3])
        ]

    def _bandBuild(self, itemList):
        if len(itemList) == 0:
            return []

        heightList = []

        for a in range(len(itemList)):
            heightList.append(itemList[a]["bbox"][3] - itemList[a]["bbox"][1])

        heightList.sort()

        heightMaximum = heightList[int(len(heightList) / 2)] * self.levelBandHeight

        edgeList = []

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            for b in range(a + 1, len(itemList)):
                bboxOtherList = itemList[b]["bbox"]

                overlap = self._overlap(bboxList[1], bboxList[3], bboxOtherList[1], bboxOtherList[3])

                ratio = overlap / min(bboxList[3] - bboxList[1], bboxOtherList[3] - bboxOtherList[1])

                if ratio < self.levelBandOverlap:
                    continue

                edgeList.append({"ratio": ratio, "first": a, "second": b})

        edgeList.sort(key=lambda edgeObject: -edgeObject["ratio"])

        parentList = []
        rangeList = []

        for a in range(len(itemList)):
            parentList.append(a)
            rangeList.append([itemList[a]["bbox"][1], itemList[a]["bbox"][3], itemList[a]["bbox"][3] - itemList[a]["bbox"][1]])

        def rootFind(index):
            while parentList[index] != index:
                parentList[index] = parentList[parentList[index]]

                index = parentList[index]

            return index

        for a in range(len(edgeList)):
            rootFirst = rootFind(edgeList[a]["first"])
            rootSecond = rootFind(edgeList[a]["second"])

            if rootFirst == rootSecond:
                continue

            start = min(rangeList[rootFirst][0], rangeList[rootSecond][0])
            end = max(rangeList[rootFirst][1], rangeList[rootSecond][1])

            heightItem = max(rangeList[rootFirst][2], rangeList[rootSecond][2])

            if end - start > max(heightMaximum, min(heightItem, heightMaximum * self.levelBandItem)):
                continue

            parentList[rootFirst] = rootSecond

            rangeList[rootSecond] = [start, end, heightItem]

        groupObject = {}

        for a in range(len(itemList)):
            root = rootFind(a)

            if root not in groupObject:
                groupObject[root] = []

            groupObject[root].append(itemList[a])

        bandList = []

        for root in groupObject:
            bboxList = list(groupObject[root][0]["bbox"])

            for a in range(len(groupObject[root])):
                bboxList = self._bboxExpand(bboxList, groupObject[root][a]["bbox"])

            bandList.append({"bbox": bboxList, "itemList": groupObject[root]})

        return sorted(bandList, key=lambda bandObject: bandObject["bbox"][1])

    def _textClean(self, text):
        result = ""

        for a in range(len(text)):
            if unicodedata.category(text[a]) not in ["Zs", "Cc"]:
                result += text[a]

        return result

    def _wideCheck(self, character):
        return unicodedata.east_asian_width(character) in ["W", "F"]

    def _spaceNormalize(self, text):
        result = ""

        for a in range(len(text)):
            if unicodedata.category(text[a]) == "Zs" and len(result) > 0 and a < len(text) - 1:
                previous = result[len(result) - 1]
                following = text[a + 1]

                if self._wideCheck(previous) and self._wideCheck(following):
                    continue

                if unicodedata.category(following) == "Zs":
                    continue

            result += text[a]

        return result.strip()

    def _symbolCheck(self, text):
        if len(text) == 0:
            return False

        for a in range(len(text)):
            if unicodedata.category(text[a])[0] not in ["P", "S"]:
                return False

        return True

    def _numberCheck(self, text):
        while len(text) > 1 and unicodedata.category(text[0]) == "Ps":
            text = text[1:]

        while len(text) > 1 and unicodedata.category(text[-1]) == "Pe":
            text = text[:-1]

        if len(text) == 0:
            return False

        for a in range(len(text)):
            category = unicodedata.category(text[a])

            if category == "Nd":
                continue

            if (category[0] == "P" or category in ["Sc", "Sk", "So"]) and a > 0 and a < len(text) - 1 and unicodedata.category(text[a - 1]) == "Nd" and unicodedata.category(text[a + 1]) == "Nd":
                continue

            return False

        return True

    def _zeroCheck(self, text):
        if len(text) < 2:
            return False

        for a in range(len(text)):
            if unicodedata.category(text[a]) != "Nd" or unicodedata.digit(text[a]) != 0:
                return False

        return True

    def _formulaCheck(self, text):
        if unicodedata.category(text[0]) == "Ps" and unicodedata.category(text[-1]) == "Pe":
            return True

        countLetter = 0

        while countLetter < len(text) and unicodedata.category(text[countLetter])[0] == "L":
            countLetter += 1

        if countLetter > self.countUnitMaximum:
            return False

        for a in range(len(text)):
            if unicodedata.category(text[a]) == "Sm":
                return True

        return False

    def _digitValue(self, text):
        digitText = ""

        for a in range(len(text)):
            if unicodedata.category(text[a]) == "Nd":
                digitText += text[a]

        if len(digitText) == 0:
            return -1

        return self._numberValue(digitText)

    def _numberValue(self, text):
        result = 0

        for a in range(len(text)):
            if unicodedata.category(text[a]) != "Nd":
                return -1

            result = result * 10 + unicodedata.digit(text[a])

        return result

    def _heightMedian(self, itemList):
        heightList = []

        for a in range(len(itemList)):
            heightList.append(itemList[a]["bbox"][3] - itemList[a]["bbox"][1])

        heightList.sort()

        return heightList[int(len(heightList) / 2)]

    def _overlap(self, start1, end1, start2, end2):
        return min(end1, end2) - max(start1, start2)

    def _rangeCheck(self, bboxList, bboxOtherList):
        overlap = self._overlap(bboxList[1], bboxList[3], bboxOtherList[1], bboxOtherList[3])

        return overlap > min(bboxList[3] - bboxList[1], bboxOtherList[3] - bboxOtherList[1]) * self.levelRowOverlap

    def _operatorContain(self, text):
        for a in range(len(text)):
            if unicodedata.category(text[a]) in ["Sm", "Pd"]:
                return True

        return False

    def _formulaSplit(self, itemList):
        resultList = []

        for a in range(len(itemList)):
            text = itemList[a]["text"]

            indexSplit = -1
            countLetter = 0

            for b in range(len(text)):
                category = unicodedata.category(text[b])

                if category == "Ps" and countLetter > self.countUnitMaximum and self._letterContain(text[b:]) == False and self._operatorContain(text[b:]) and self._formulaCheck(self._textClean(text[b:])):
                    indexSplit = b

                    break

                if category[0] == "L":
                    countLetter += 1
                elif category[0] in ["P", "S"]:
                    break

            if indexSplit < 0:
                resultList.append(itemList[a])

                continue

            charList = self._charPosition(itemList[a])

            if len(charList) != len(text):
                charList = self._charPosition({"text": text, "bbox": itemList[a]["bbox"]})

            bboxList = itemList[a]["bbox"]

            keyObject = dict(itemList[a])
            keyObject["text"] = text[0:indexSplit].strip()
            keyObject["bbox"] = [bboxList[0], bboxList[1], charList[indexSplit - 1]["end"], bboxList[3]]
            keyObject["charList"] = charList[0:indexSplit]

            formulaObject = dict(itemList[a])
            formulaObject["text"] = text[indexSplit:]
            formulaObject["bbox"] = [charList[indexSplit]["start"], bboxList[1], bboxList[2], bboxList[3]]
            formulaObject["charList"] = charList[indexSplit:]

            resultList.append(keyObject)
            resultList.append(formulaObject)

        return resultList

    def _typeAssign(self, itemList):
        for a in range(len(itemList)):
            text = self._textClean(itemList[a]["text"])

            if self._zeroCheck(text):
                itemList[a]["type"] = "suffix"
            elif self._numberCheck(text):
                itemList[a]["type"] = "value"
            elif len(text) > 0 and self._formulaCheck(text):
                itemList[a]["type"] = "formula"
            else:
                itemList[a]["type"] = "key"

    def _formulaContinue(self, itemList, height, lineObject):
        horizontalList = lineObject["horizontalList"]

        isChanged = True

        while isChanged:
            isChanged = False

            for a in range(len(itemList)):
                if itemList[a]["type"] != "formula":
                    continue

                text = itemList[a]["text"]

                countOpen = 0

                for b in range(len(text)):
                    category = unicodedata.category(text[b])

                    if category == "Ps":
                        countOpen += 1
                    elif category == "Pe":
                        countOpen -= 1

                bboxList = itemList[a]["bbox"]

                textClean = self._textClean(text)

                isOperator = len(textClean) > 0 and unicodedata.category(textClean[-1]) == "Sm"

                for b in range(len(itemList)):
                    bboxOtherList = itemList[b]["bbox"]

                    gap = bboxOtherList[0] - bboxList[2]

                    if itemList[b]["type"] not in ["value", "key"] or gap < -height * self.levelMargin or gap > height * self.levelUnitGap or self._rangeCheck(bboxList, bboxOtherList) == False:
                        continue

                    if itemList[b]["type"] == "key" and self._letterContain(itemList[b]["text"]):
                        continue

                    if isOperator == False and self._wallCheck(lineObject["verticalList"], bboxList[2] - height * self.levelMargin, bboxOtherList[0] + height * self.levelMargin, bboxOtherList):
                        continue

                    itemList[b]["type"] = "formula"

                    isChanged = True

                if countOpen <= 0:
                    continue

                for b in range(len(itemList)):
                    bboxOtherList = itemList[b]["bbox"]

                    if itemList[b]["type"] != "key":
                        continue

                    if self._overlap(bboxList[0], bboxList[2], bboxOtherList[0], bboxOtherList[2]) <= 0:
                        continue

                    gap = bboxOtherList[1] - bboxList[3]

                    if gap < -height * self.levelMargin or gap > height * self.levelLineGap or self._ruleBetweenCheck(horizontalList, bboxList, bboxOtherList):
                        continue

                    itemList[b]["type"] = "formula"

                    isChanged = True

    def _rowDetect(self, itemList, height):
        numberList = []

        for a in range(len(itemList)):
            text = self._textClean(itemList[a]["text"])

            countDigit = 0

            for b in range(len(text)):
                if unicodedata.category(text[b]) == "Nd":
                    countDigit += 1

            if itemList[a]["type"] in ["value", "formula"] and countDigit > 0 and countDigit <= self.countRowDigit and countDigit * 2 >= len(text):
                numberList.append(itemList[a])

        columnList = []

        for a in range(len(numberList)):
            centerX = (numberList[a]["bbox"][0] + numberList[a]["bbox"][2]) / 2

            isAdded = False

            for b in range(len(columnList)):
                if abs(columnList[b]["centerX"] - centerX) <= height * self.levelRowColumn:
                    columnList[b]["itemList"].append(numberList[a])

                    isAdded = True

                    break

            if isAdded == False:
                columnList.append({"centerX": centerX, "itemList": [numberList[a]]})

        for a in range(len(columnList)):
            columnItemList = sorted(columnList[a]["itemList"], key=lambda itemObject: itemObject["bbox"][1])

            valueOtherList = []

            for b in range(len(columnList)):
                if b == a:
                    continue

                for c in range(len(columnList[b]["itemList"])):
                    otherObject = columnList[b]["itemList"][c]

                    valueOtherList.append({"value": self._digitValue(self._textClean(otherObject["text"])), "y": (otherObject["bbox"][1] + otherObject["bbox"][3]) / 2})

            runList = [columnItemList[0]]

            for b in range(1, len(columnItemList) + 1):
                valueLast = self._digitValue(self._textClean(runList[len(runList) - 1]["text"]))

                isContinue = b < len(columnItemList) and self._rowStepCheck(valueLast, self._digitValue(self._textClean(columnItemList[b]["text"])), valueOtherList, columnItemList[b]["bbox"][3], self._slotCount(itemList, columnList, runList[len(runList) - 1]["bbox"][3], columnItemList[b]["bbox"][1]))

                if isContinue == False and b + 1 < len(columnItemList) and self._digitValue(self._textClean(columnItemList[b + 1]["text"])) == valueLast + 2:
                    columnItemList[b]["text"] = str(valueLast + 1)

                    isContinue = True

                if isContinue:
                    runList.append(columnItemList[b])

                    continue

                if len(runList) >= self.countRowMinimum:
                    for c in range(len(runList)):
                        runList[c]["type"] = "row"
                        runList[c]["text"] = str(self._digitValue(self._textClean(runList[c]["text"])))

                if b < len(columnItemList):
                    runList = [columnItemList[b]]

    def _slotCount(self, itemList, columnList, top, bottom):
        numberList = []
        rangeList = []

        for a in range(len(columnList)):
            left = None
            right = None

            for b in range(len(columnList[a]["itemList"])):
                bboxColumnList = columnList[a]["itemList"][b]["bbox"]

                numberList.append(columnList[a]["itemList"][b])

                left = bboxColumnList[0] if left == None else min(left, bboxColumnList[0])
                right = bboxColumnList[2] if right == None else max(right, bboxColumnList[2])

            rangeList.append([left, right])

        count = 0

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            if itemList[a] in numberList or centerY <= top or centerY >= bottom:
                continue

            for b in range(len(rangeList)):
                left = rangeList[b][0]
                right = rangeList[b][1]

                if centerX >= left and centerX <= right and bboxList[2] - bboxList[0] <= (right - left) * self.levelRowSlot:
                    count += 1

                    break

        return count

    def _rowStepCheck(self, valueLast, value, valueOtherList, bottom, countSlot):
        if value <= valueLast:
            return False

        countMissing = 0

        for a in range(valueLast + 1, value):
            isPresent = False

            for b in range(len(valueOtherList)):
                if valueOtherList[b]["value"] == a and valueOtherList[b]["y"] <= bottom:
                    isPresent = True

                    break

            if isPresent == False:
                countMissing += 1

        return countMissing - countSlot <= self.countRowMissing

    def _labelNext(self, chainList, lineSortedList, usedList):
        lastObject = chainList[len(chainList) - 1]

        if self._bareNumberCheck(self._textClean(lastObject["text"])) == False:
            return None

        labelList = []

        for a in range(len(chainList)):
            text = self._textClean(chainList[a]["text"])

            if len(text) > 0 and len(text) <= self.countUnitMaximum and self._bareNumberCheck(text) == False:
                labelList.append(chainList[a])

        if len(labelList) < self.countLabelMinimum:
            return None

        pitchList = []

        for a in range(1, len(labelList)):
            pitchList.append(labelList[a]["bbox"][0] - labelList[a - 1]["bbox"][0])

        pitch = sum(pitchList) / len(pitchList)

        if pitch <= 0 or max(pitchList) - min(pitchList) > pitch * self.levelCellSize:
            return None

        labelLast = labelList[len(labelList) - 1]

        countLabel = len(self._textClean(labelLast["text"]))

        positionNext = labelLast["bbox"][0] + pitch

        for a in range(len(lineSortedList)):
            candidateObject = lineSortedList[a]

            text = candidateObject["text"]

            if candidateObject in chainList or candidateObject in usedList or len(text) <= countLabel or text != text.strip() or self._rangeCheck(candidateObject["bbox"], lastObject["bbox"]) == False:
                continue

            if abs(candidateObject["bbox"][0] - positionNext) > pitch * self.levelCellSize or unicodedata.category(text[0]) == "Nd":
                continue

            charList = self._charPosition(candidateObject)

            if len(charList) != len(text):
                charList = self._charPosition({"text": text, "bbox": candidateObject["bbox"]})

            bboxList = candidateObject["bbox"]

            labelObject = dict(candidateObject)
            labelObject["text"] = text[0:countLabel]
            labelObject["bbox"] = [bboxList[0], bboxList[1], charList[countLabel - 1]["end"], bboxList[3]]
            labelObject["charList"] = charList[0:countLabel]

            restObject = dict(candidateObject)
            restObject["text"] = text[countLabel:]
            restObject["bbox"] = [charList[countLabel]["start"], bboxList[1], bboxList[2], bboxList[3]]
            restObject["charList"] = charList[countLabel:]

            return {"label": labelObject, "rest": restObject, "source": candidateObject}

        return None

    def _valueCompose(self, itemList, verticalList, height):
        resultList = []

        usedList = []

        lineSortedList = sorted(itemList, key=lambda itemObject: itemObject["bbox"][0])

        for a in range(len(lineSortedList)):
            itemObject = lineSortedList[a]

            if itemObject in usedList:
                continue

            if itemObject["type"] not in ["value", "suffix"] or itemObject.get("isEnclosed"):
                continue

            chainList = [itemObject]

            isExtended = True

            while isExtended:
                isExtended = False

                lastObject = chainList[len(chainList) - 1]

                nextObject = None

                for b in range(len(lineSortedList)):
                    candidateObject = lineSortedList[b]

                    if candidateObject in chainList or candidateObject in usedList or candidateObject["type"] == "row" or candidateObject.get("isEnclosed"):
                        continue

                    if candidateObject["bbox"][0] < lastObject["bbox"][2] - height * self.levelMargin:
                        continue

                    if self._rangeCheck(candidateObject["bbox"], lastObject["bbox"]) == False:
                        continue

                    if nextObject == None or candidateObject["bbox"][0] < nextObject["bbox"][0]:
                        nextObject = candidateObject

                if nextObject == None:
                    continue

                gap = nextObject["bbox"][0] - lastObject["bbox"][2]

                text = self._textClean(nextObject["text"])

                isNumber = nextObject["type"] in ["value", "suffix"]
                heightMaximum = max(nextObject["bbox"][3] - nextObject["bbox"][1], lastObject["bbox"][3] - lastObject["bbox"][1])

                isUnit = len(text) <= self.countUnitMaximum and self._bareNumberCheck(text) == False and lastObject["type"] in ["value", "suffix"] and gap <= heightMaximum * self.levelUnitGap
                isSymbol = self._symbolCheck(text) and gap <= height * self.levelUnitGap

                heightPair = min(nextObject["bbox"][3] - nextObject["bbox"][1], lastObject["bbox"][3] - lastObject["bbox"][1])

                heightNext = nextObject["bbox"][3] - nextObject["bbox"][1]
                heightFirst = chainList[0]["bbox"][3] - chainList[0]["bbox"][1]

                if isNumber and abs(heightNext - heightFirst) > max(heightNext, heightFirst) * self.levelCellSize:
                    isNumber = False

                bboxSpanList = [0, max(nextObject["bbox"][1], lastObject["bbox"][1]), 0, min(nextObject["bbox"][3], lastObject["bbox"][3])]

                isColumn = len(self._textClean(lastObject["text"])) >= 2 and len(text) >= 2 and self._wallCheck(verticalList, lastObject["bbox"][2] - height * self.levelMargin, nextObject["bbox"][0] + height * self.levelMargin, bboxSpanList)

                if isColumn and (self._wallCheck(verticalList, lastObject["bbox"][0] + height * self.levelMargin, lastObject["bbox"][2] - height * self.levelMargin, lastObject["bbox"]) or self._wallCheck(verticalList, nextObject["bbox"][0] + height * self.levelMargin, nextObject["bbox"][2] - height * self.levelMargin, nextObject["bbox"])):
                    isColumn = False

                if isUnit and isNumber == False and self._wallCount(verticalList, lastObject["bbox"][2] - height * self.levelMargin, nextObject["bbox"][0] + height * self.levelMargin, bboxSpanList) > 1:
                    isUnit = False

                if ((isNumber and gap <= heightPair * self.levelComposeGap) or isUnit or isSymbol) and isColumn == False:
                    chainList.append(nextObject)

                    isExtended = True

            while len(chainList) > 1 and chainList[len(chainList) - 1]["type"] not in ["value", "suffix"] and self._symbolCheck(self._textClean(chainList[len(chainList) - 1]["text"])):
                chainList.pop()

            labelObject = self._labelNext(chainList, lineSortedList, usedList)

            if labelObject != None:
                chainList.append(labelObject["label"])

                usedList.append(labelObject["source"])

                resultList.append(labelObject["rest"])

            for b in range(len(lineSortedList)):
                candidateObject = lineSortedList[b]

                if candidateObject in chainList or candidateObject in usedList or self._symbolCheck(self._textClean(candidateObject["text"])) == False:
                    continue

                gap = chainList[0]["bbox"][0] - candidateObject["bbox"][2]

                textCandidate = self._textClean(candidateObject["text"])

                gapLimit = height * self.levelComposeGap if unicodedata.category(textCandidate[-1:] or " ") == "Ps" else height * self.levelUnitGap

                if gap >= -height * self.levelMargin and gap <= gapLimit and self._rangeCheck(candidateObject["bbox"], chainList[0]["bbox"]):
                    chainList.insert(0, candidateObject)

                    break

            if len(chainList) == 1:
                continue

            text = ""

            bboxList = list(chainList[0]["bbox"])

            for b in range(len(chainList)):
                textPart = chainList[b]["text"].strip()

                if len(text) > 0 and len(textPart) > 0 and (unicodedata.category(text[-1]) != "Nd" or unicodedata.category(textPart[0]) != "Nd" or chainList[b]["bbox"][0] - chainList[b - 1]["bbox"][2] > min(chainList[b]["bbox"][3] - chainList[b]["bbox"][1], chainList[b - 1]["bbox"][3] - chainList[b - 1]["bbox"][1]) * self.levelDigitGap):
                    text += " "

                text += textPart

                bboxList = [min(bboxList[0], chainList[b]["bbox"][0]), min(bboxList[1], chainList[b]["bbox"][1]), max(bboxList[2], chainList[b]["bbox"][2]), max(bboxList[3], chainList[b]["bbox"][3])]

                usedList.append(chainList[b])

            resultList.append({"text": text, "bbox": bboxList, "type": "value", "page": chainList[0].get("page", 1), "partList": chainList})

        for a in range(len(itemList)):
            if itemList[a] not in usedList:
                if itemList[a]["type"] == "suffix":
                    itemList[a]["type"] = "value"

                resultList.append(itemList[a])

        resultList.sort(key=lambda itemObject: (itemObject["bbox"][1], itemObject["bbox"][0]))

        return resultList

    def _charPosition(self, itemObject):
        if len(itemObject.get("charList", [])) > 0:
            return itemObject["charList"]

        text = itemObject["text"]

        bboxList = itemObject["bbox"]

        width = (bboxList[2] - bboxList[0]) / max(len(text), 1)

        resultList = []

        for a in range(len(text)):
            resultList.append({"text": text[a], "start": bboxList[0] + width * a, "end": bboxList[0] + width * (a + 1)})

        return resultList

    def _enclosedText(self, number):
        if number >= 1 and number <= 20:
            return chr(0x2460 + number - 1)

        if number >= 21 and number <= 35:
            return chr(0x3251 + number - 21)

        if number >= 36 and number <= 50:
            return chr(0x32B1 + number - 36)

        return f"({number})"

    def _overlayJoin(self, itemList):
        removeList = []

        for a in range(len(itemList)):
            numberObject = itemList[a]

            text = self._textClean(numberObject["text"])

            if self._numberValue(text) < 0 or len(text) > 2:
                continue

            bboxNumberList = numberObject["bbox"]

            centerX = (bboxNumberList[0] + bboxNumberList[2]) / 2
            centerY = (bboxNumberList[1] + bboxNumberList[3]) / 2

            enclosureObject = None

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                textEnclosure = self._textClean(itemList[b]["text"])

                if b == a or len(textEnclosure) != 1 or unicodedata.category(textEnclosure) == "Nd" or itemList[b] in removeList:
                    continue

                if bboxList[0] <= centerX and bboxList[2] >= centerX and bboxList[1] <= centerY and bboxList[3] >= centerY:
                    enclosureObject = itemList[b]

                    break

            if enclosureObject == None:
                if self._overlaySymbolReplace(itemList, numberObject, removeList, centerX, centerY):
                    removeList.append(numberObject)

                continue

            numberObject["isEnclosed"] = True

            hostObject = None

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                if itemList[b] is numberObject or itemList[b] is enclosureObject or itemList[b] in removeList:
                    continue

                if bboxList[0] <= centerX and bboxList[2] >= centerX and bboxList[1] <= centerY and bboxList[3] >= centerY:
                    if hostObject == None or (bboxList[2] - bboxList[0]) < (hostObject["bbox"][2] - hostObject["bbox"][0]):
                        hostObject = itemList[b]

            if hostObject == None:
                continue

            charList = self._charPosition(hostObject)

            insertIndex = len(charList)

            for b in range(len(charList)):
                if (charList[b]["start"] + charList[b]["end"]) / 2 > centerX:
                    insertIndex = b

                    break

            enclosed = self._enclosedText(self._numberValue(text))

            characterList = []

            for b in range(len(charList)):
                characterList.append(charList[b]["text"])

            characterList.insert(insertIndex, enclosed)

            hostObject["text"] = "".join(characterList)
            hostObject["charList"] = []

            removeList.append(numberObject)
            removeList.append(enclosureObject)

        resultList = []

        for a in range(len(itemList)):
            if itemList[a] not in removeList:
                resultList.append(itemList[a])

        return resultList

    def _enclosedMark(self, itemList, ringList):
        for a in range(len(itemList)):
            text = self._textClean(itemList[a]["text"])

            if self._numberValue(text) < 0 or len(text) > 2:
                continue

            bboxList = itemList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            for b in range(len(ringList)):
                bboxRingList = ringList[b]["bbox"]

                if bboxRingList[0] <= centerX and bboxRingList[2] >= centerX and bboxRingList[1] <= centerY and bboxRingList[3] >= centerY:
                    itemList[a]["isEnclosed"] = True

                    break

    def _overlaySymbolReplace(self, itemList, numberObject, removeList, centerX, centerY):
        hostObject = None
        indexHost = -1

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            if itemList[a] is numberObject or itemList[a] in removeList:
                continue

            if bboxList[0] > centerX or bboxList[2] < centerX or bboxList[1] > centerY or bboxList[3] < centerY:
                continue

            charList = self._charPosition(itemList[a])

            for b in range(len(charList)):
                if charList[b]["start"] <= centerX and charList[b]["end"] >= centerX and unicodedata.category(charList[b]["text"][0:1] or " ") == "So":
                    if hostObject == None or (bboxList[2] - bboxList[0]) < (hostObject["bbox"][2] - hostObject["bbox"][0]):
                        hostObject = itemList[a]
                        indexHost = b

                    break

        if hostObject == None:
            return False

        charList = list(self._charPosition(hostObject))

        charList[indexHost] = {"text": self._enclosedText(self._numberValue(self._textClean(numberObject["text"]))), "start": charList[indexHost]["start"], "end": charList[indexHost]["end"]}

        textList = []

        for a in range(len(charList)):
            textList.append(charList[a]["text"])

        hostObject["text"] = "".join(textList)
        hostObject["charList"] = charList

        return True

    def _gapInsert(self, itemList):
        removeList = []

        for a in range(len(itemList)):
            insertObject = itemList[a]

            text = self._textClean(insertObject["text"])

            if len(text) == 0 or len(text) > self.countUnitMaximum:
                continue

            bboxInsertList = insertObject["bbox"]

            centerX = (bboxInsertList[0] + bboxInsertList[2]) / 2

            for b in range(len(itemList)):
                hostObject = itemList[b]

                if b == a or hostObject in removeList or len(hostObject.get("charList", [])) < 2:
                    continue

                bboxHostList = hostObject["bbox"]

                if centerX <= bboxHostList[0] or centerX >= bboxHostList[2] or self._rangeCheck(bboxHostList, bboxInsertList) == False:
                    continue

                charList = hostObject["charList"]

                indexInsert = -1

                for c in range(len(charList) - 1):
                    if charList[c]["end"] <= centerX and charList[c + 1]["start"] >= centerX and charList[c + 1]["start"] - charList[c]["end"] >= (bboxInsertList[2] - bboxInsertList[0]) * self.levelInsertRoom:
                        indexInsert = c + 1

                        break

                if indexInsert < 0:
                    continue

                charInsertList = []

                for c in range(len(text)):
                    charInsertList.append({"text": text[c], "start": bboxInsertList[0], "end": bboxInsertList[2]})

                hostObject["charList"] = charList[0:indexInsert] + charInsertList + charList[indexInsert:]

                textList = []

                for c in range(len(hostObject["charList"])):
                    if c > 0 and hostObject["charList"][c]["start"] - hostObject["charList"][c - 1]["end"] > (hostObject["bbox"][3] - hostObject["bbox"][1]) and hostObject["charList"][c]["text"] not in text and hostObject["charList"][c - 1]["text"] not in text:
                        textList.append(" ")

                    textList.append(hostObject["charList"][c]["text"])

                hostObject["text"] = "".join(textList)

                removeList.append(insertObject)

                break

        resultList = []

        for a in range(len(itemList)):
            if itemList[a] not in removeList:
                resultList.append(itemList[a])

        return resultList

    def _ringArtifactRemove(self, itemList, ringList):
        resultList = []

        for a in range(len(itemList)):
            isArtifact = False

            if len(self._textClean(itemList[a]["text"])) <= self.countUnitMaximum:
                for b in range(len(ringList)):
                    if self._iou(itemList[a]["bbox"], ringList[b]["bbox"]) >= self.levelRingArtifact:
                        isArtifact = True

                        break

            if isArtifact == False:
                resultList.append(itemList[a])

        return resultList

    def _iou(self, bboxList, bboxOtherList):
        width = min(bboxList[2], bboxOtherList[2]) - max(bboxList[0], bboxOtherList[0])
        height = min(bboxList[3], bboxOtherList[3]) - max(bboxList[1], bboxOtherList[1])

        if width <= 0 or height <= 0:
            return 0

        area = width * height

        return area / ((bboxList[2] - bboxList[0]) * (bboxList[3] - bboxList[1]) + (bboxOtherList[2] - bboxOtherList[0]) * (bboxOtherList[3] - bboxOtherList[1]) - area)

    def _verticalBoxCollect(self, itemList, verticalList):
        resultList = []

        for a in range(len(itemList)):
            if itemList[a].get("isVertical") and len(self._textClean(itemList[a]["text"])) >= 2:
                verticalList.append({"text": self._textClean(itemList[a]["text"]), "bbox": itemList[a]["bbox"]})

                continue

            resultList.append(itemList[a])

        insideList = []

        for a in range(len(resultList)):
            bboxList = resultList[a]["bbox"]

            area = (bboxList[2] - bboxList[0]) * (bboxList[3] - bboxList[1])

            for b in range(len(verticalList)):
                bboxVerticalList = verticalList[b]["bbox"]

                areaInside = max(0, min(bboxVerticalList[2], bboxList[2]) - max(bboxVerticalList[0], bboxList[0])) * max(0, min(bboxVerticalList[3], bboxList[3]) - max(bboxVerticalList[1], bboxList[1]))

                if area > 0 and areaInside >= area * self.levelContain:
                    insideList.append(resultList[a])

                    break

        outsideList = []

        for a in range(len(resultList)):
            if resultList[a] not in insideList:
                outsideList.append(resultList[a])

        return outsideList

    def _arcFit(self, itemList, height):
        candidateList = []

        for a in range(len(itemList)):
            text = self._textClean(itemList[a]["text"])

            if len(text) == 0 or len(text) > self.countUnitMaximum:
                continue

            candidateList.append(itemList[a])

        usedList = []

        resultList = []

        for a in range(len(candidateList)):
            if candidateList[a] in usedList:
                continue

            bboxList = candidateList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            groupList = []

            for b in range(len(candidateList)):
                bboxOtherList = candidateList[b]["bbox"]

                if candidateList[b] in usedList or math.hypot((bboxOtherList[0] + bboxOtherList[2]) / 2 - centerX, (bboxOtherList[1] + bboxOtherList[3]) / 2 - centerY) > height * self.levelArcNeighbor:
                    continue

                groupList.append(candidateList[b])

            if len(groupList) < self.countArcMinimum:
                continue

            pointList = []

            for b in range(len(groupList)):
                bboxOtherList = groupList[b]["bbox"]

                pointList.append([(bboxOtherList[0] + bboxOtherList[2]) / 2, (bboxOtherList[1] + bboxOtherList[3]) / 2])

            pointArray = numpy.array(pointList, dtype=float)

            matrix = numpy.column_stack([pointArray[:, 0], pointArray[:, 1], numpy.ones(len(pointArray))])
            vector = -(pointArray[:, 0] ** 2 + pointArray[:, 1] ** 2)

            solution = numpy.linalg.lstsq(matrix, vector, rcond=None)[0]

            circleX = -solution[0] / 2
            circleY = -solution[1] / 2

            radiusSquare = circleX ** 2 + circleY ** 2 - solution[2]

            if radiusSquare <= 0:
                continue

            radius = math.sqrt(radiusSquare)

            distanceList = numpy.hypot(pointArray[:, 0] - circleX, pointArray[:, 1] - circleY)

            if radius < height * self.levelArcRadiusMinimum or radius > height * self.levelArcRadiusMaximum or float(numpy.max(numpy.abs(distanceList - radius))) > radius * self.levelArcResidual:
                continue

            angleList = []

            for b in range(len(pointList)):
                angle = math.degrees(math.atan2(pointList[b][1] - circleY, pointList[b][0] - circleX))

                if angle < 90:
                    angle += 360

                angleList.append(angle)

            if max(angleList) - min(angleList) < self.angleArcMinimum:
                continue

            angleSortedList = sorted(angleList)

            gapList = []

            for b in range(len(angleSortedList) - 1):
                gapList.append(angleSortedList[b + 1] - angleSortedList[b])

            if max(gapList) > sum(gapList) / len(gapList) * self.levelArcUniform:
                continue

            isEmpty = True

            for b in range(len(itemList)):
                bboxOtherList = itemList[b]["bbox"]

                if itemList[b] not in groupList and math.hypot((bboxOtherList[0] + bboxOtherList[2]) / 2 - circleX, (bboxOtherList[1] + bboxOtherList[3]) / 2 - circleY) < radius * self.levelArcInner:
                    isEmpty = False

                    break

            if isEmpty == False:
                continue

            orderList = sorted(range(len(groupList)), key=lambda index: angleList[index])

            textList = []

            bboxArcList = list(groupList[0]["bbox"])

            for b in range(len(orderList)):
                itemObject = groupList[orderList[b]]

                textList.append(self._textClean(itemObject["text"]))

                bboxArcList = [min(bboxArcList[0], itemObject["bbox"][0]), min(bboxArcList[1], itemObject["bbox"][1]), max(bboxArcList[2], itemObject["bbox"][2]), max(bboxArcList[3], itemObject["bbox"][3])]

                usedList.append(itemObject)

            resultList.append({"text": "".join(textList), "bbox": bboxArcList, "page": groupList[0].get("page", 1), "isVertical": False, "charList": []})

        for a in range(len(itemList)):
            if itemList[a] not in usedList:
                resultList.append(itemList[a])

        return resultList

    def _markApply(self, itemList, markList):
        for a in range(len(markList)):
            bboxMarkList = markList[a]["bbox"]

            centerX = (bboxMarkList[0] + bboxMarkList[2]) / 2
            centerY = (bboxMarkList[1] + bboxMarkList[3]) / 2

            itemBest = None
            distanceBest = -1

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                if self._overlap(bboxList[0], bboxList[2], bboxMarkList[0], bboxMarkList[2]) <= 0 or self._overlap(bboxList[1], bboxList[3], bboxMarkList[1], bboxMarkList[3]) <= 0:
                    continue

                distance = abs((bboxList[0] + bboxList[2]) / 2 - centerX) + abs((bboxList[1] + bboxList[3]) / 2 - centerY)

                if distanceBest < 0 or distance < distanceBest:
                    distanceBest = distance
                    itemBest = itemList[b]

            if itemBest != None:
                itemBest["isMark"] = True

    def _optionApply(self, itemList, circleList):
        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            for b in range(len(circleList)):
                bboxCircleList = circleList[b]["bbox"]

                if self._overlap(bboxList[0], bboxList[2], bboxCircleList[0], bboxCircleList[2]) > 0 and bboxCircleList[1] <= centerY and bboxCircleList[3] >= centerY:
                    itemList[a]["isOption"] = True
                    itemList[a]["circleIndex"] = b

                    break

            if itemList[a].get("isMark"):
                itemList[a]["isOption"] = True

    def _letterMerge(self, itemList, height):
        itemSortedList = sorted(itemList, key=lambda itemObject: itemObject["bbox"][0])

        resultList = []

        usedList = []

        for a in range(len(itemSortedList)):
            bboxList = itemSortedList[a]["bbox"]

            for b in range(len(itemSortedList)):
                bboxOtherList = itemSortedList[b]["bbox"]

                text = self._textClean(itemSortedList[b]["text"])

                if b == a or len(text) == 0 or unicodedata.category(text[-1]) != "Nd":
                    continue

                gap = bboxList[0] - bboxOtherList[2]

                if gap >= -height * self.levelMargin and gap <= height * self.levelUnitGap and self._rangeCheck(bboxList, bboxOtherList):
                    itemSortedList[a]["isUnit"] = True

                    break

        for a in range(len(itemSortedList)):
            itemObject = itemSortedList[a]

            if itemObject in usedList:
                continue

            if self._letterCheck(itemObject) == False:
                resultList.append(itemObject)

                continue

            chainList = [itemObject]

            isExtended = True

            while isExtended:
                isExtended = False

                lastObject = chainList[len(chainList) - 1]

                bboxLastList = lastObject["bbox"]

                width = bboxLastList[2] - bboxLastList[0]

                for b in range(len(itemSortedList)):
                    candidateObject = itemSortedList[b]

                    if candidateObject in chainList or candidateObject in usedList or self._letterCheck(candidateObject) == False:
                        continue

                    bboxList = candidateObject["bbox"]

                    gap = bboxList[0] - bboxLastList[2]

                    if gap < width * self.levelLetterMinimum or gap > width * self.levelLetterGap:
                        continue

                    if self._rangeCheck(bboxList, bboxLastList) == False or abs((bboxList[3] - bboxList[1]) - (bboxLastList[3] - bboxLastList[1])) > height * self.levelMargin * 2:
                        continue

                    chainList.append(candidateObject)

                    isExtended = True

                    break

            if len(chainList) == 1:
                resultList.append(itemObject)

                continue

            textList = []

            bboxList = list(chainList[0]["bbox"])

            for b in range(len(chainList)):
                textList.append(chainList[b]["text"].strip())

                bboxList = [min(bboxList[0], chainList[b]["bbox"][0]), min(bboxList[1], chainList[b]["bbox"][1]), max(bboxList[2], chainList[b]["bbox"][2]), max(bboxList[3], chainList[b]["bbox"][3])]

                usedList.append(chainList[b])

            resultList.append({"text": "".join(textList), "bbox": bboxList, "page": chainList[0].get("page", 1), "isVertical": False})

        return resultList

    def _verticalPair(self, itemList, verticalList, height):
        usedList = []

        for a in range(len(itemList)):
            firstObject = itemList[a]

            if firstObject in usedList or self._letterCheck(firstObject) == False or self._isolatedCheck(firstObject, itemList, height) == False:
                continue

            bboxFirstList = firstObject["bbox"]

            sizeFirst = bboxFirstList[3] - bboxFirstList[1]

            for b in range(len(itemList)):
                secondObject = itemList[b]

                if b == a or secondObject in usedList or self._letterCheck(secondObject) == False:
                    continue

                bboxSecondList = secondObject["bbox"]

                sizeSecond = bboxSecondList[3] - bboxSecondList[1]

                gap = bboxSecondList[1] - bboxFirstList[3]

                if gap < 0 or gap > max(sizeFirst, sizeSecond) * self.levelVerticalPairGap:
                    continue

                if abs((bboxFirstList[0] + bboxFirstList[2]) / 2 - (bboxSecondList[0] + bboxSecondList[2]) / 2) > max(sizeFirst, sizeSecond) / 2:
                    continue

                if abs(sizeFirst - sizeSecond) > max(sizeFirst, sizeSecond) * self.levelVerticalPairSize or self._isolatedCheck(secondObject, itemList, height) == False:
                    continue

                verticalList.append({"text": self._textClean(firstObject["text"]) + self._textClean(secondObject["text"]), "bbox": [min(bboxFirstList[0], bboxSecondList[0]), bboxFirstList[1], max(bboxFirstList[2], bboxSecondList[2]), bboxSecondList[3]], "page": firstObject.get("page", 1)})

                usedList.append(firstObject)
                usedList.append(secondObject)

                break

        resultList = []

        for a in range(len(itemList)):
            if itemList[a] not in usedList:
                resultList.append(itemList[a])

        return resultList

    def _isolatedCheck(self, itemObject, itemList, height):
        bboxList = itemObject["bbox"]

        width = bboxList[2] - bboxList[0]

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            if itemList[a] is itemObject or self._rangeCheck(bboxOtherList, bboxList) == False:
                continue

            gap = max(bboxOtherList[0] - bboxList[2], bboxList[0] - bboxOtherList[2])

            if gap <= width * self.levelLetterGap:
                return False

        return True

    def _letterLine(self, itemList, height):
        resultList = []

        usedList = []

        for a in range(len(itemList)):
            itemObject = itemList[a]

            if itemObject in usedList or self._letterCheck(itemObject) == False:
                continue

            lineList = [itemObject]

            isOnly = True

            isAdded = True

            while isAdded and isOnly:
                isAdded = False

                for b in range(len(itemList)):
                    otherObject = itemList[b]

                    if otherObject in lineList:
                        continue

                    isNear = False

                    for c in range(len(lineList)):
                        memberObject = lineList[c]

                        if self._rangeCheck(otherObject["bbox"], memberObject["bbox"]) == False:
                            continue

                        gap = max(otherObject["bbox"][0] - memberObject["bbox"][2], memberObject["bbox"][0] - otherObject["bbox"][2])

                        if gap <= (memberObject["bbox"][2] - memberObject["bbox"][0]) * self.levelLetterLine:
                            isNear = True

                            break

                    if isNear == False:
                        continue

                    if self._letterCheck(otherObject) == False or otherObject in usedList:
                        isOnly = False

                        break

                    lineList.append(otherObject)

                    isAdded = True

            if isOnly == False or len(lineList) < 2:
                continue

            lineList.sort(key=lambda lineObject: lineObject["bbox"][0])

            textList = []

            bboxLineList = list(lineList[0]["bbox"])

            for b in range(len(lineList)):
                textList.append(self._textClean(lineList[b]["text"]))

                bboxList = lineList[b]["bbox"]

                bboxLineList = [min(bboxLineList[0], bboxList[0]), min(bboxLineList[1], bboxList[1]), max(bboxLineList[2], bboxList[2]), max(bboxLineList[3], bboxList[3])]

                usedList.append(lineList[b])

            resultList.append({"text": "".join(textList), "bbox": bboxLineList, "page": lineList[0].get("page", 1), "isVertical": False})

        for a in range(len(itemList)):
            if itemList[a] not in usedList:
                resultList.append(itemList[a])

        return resultList

    def _letterCheck(self, itemObject):
        text = self._textClean(itemObject["text"])

        if len(text) != 1 or itemObject.get("isOption") or itemObject.get("isUnit"):
            return False

        category = unicodedata.category(text)

        return category[0] == "L"

    def _titleJoin(self, verticalList, height):
        verticalSortedList = sorted(verticalList, key=lambda itemObject: itemObject["bbox"][0])

        resultList = []

        for a in range(len(verticalSortedList)):
            itemObject = verticalSortedList[a]

            bboxList = itemObject["bbox"]

            isJoined = False

            for b in range(len(resultList)):
                bboxResultList = resultList[b]["bbox"]

                overlap = self._overlap(bboxList[1], bboxList[3], bboxResultList[1], bboxResultList[3])

                if overlap < min(bboxList[3] - bboxList[1], bboxResultList[3] - bboxResultList[1]) * self.levelTitleOverlap:
                    continue

                if bboxList[0] - bboxResultList[2] > (bboxList[2] - bboxList[0]) * self.levelTitleGap:
                    continue

                if abs(bboxList[1] - bboxResultList[1]) > height:
                    continue

                resultList[b] = {"text": resultList[b]["text"] + itemObject["text"], "bbox": [bboxResultList[0], min(bboxResultList[1], bboxList[1]), bboxList[2], max(bboxResultList[3], bboxList[3])]}

                isJoined = True

                break

            if isJoined == False:
                resultList.append(dict(itemObject))

        return resultList

    def _unitAbove(self, itemList, height):
        usedList = []

        for a in range(len(itemList)):
            valueObject = itemList[a]

            if valueObject["type"] != "value":
                continue

            bboxValueList = valueObject["bbox"]

            labelList = []

            for b in range(len(itemList)):
                labelObject = itemList[b]

                bboxList = labelObject["bbox"]

                if labelObject["type"] != "key" or labelObject in usedList or len(self._textClean(labelObject["text"])) > self.countUnitMaximum:
                    continue

                if bboxList[3] > bboxValueList[1] + height * self.levelMargin or bboxValueList[1] - bboxList[3] > height * self.levelUnitAbove:
                    continue

                centerX = (bboxList[0] + bboxList[2]) / 2

                if centerX < bboxValueList[0] - height * self.levelUnitPrefix or centerX > bboxValueList[2] + height:
                    continue

                isHeader = False

                for c in range(len(itemList)):
                    bboxOtherList = itemList[c]["bbox"]

                    if itemList[c] is valueObject or itemList[c]["type"] != "value":
                        continue

                    overlap = self._overlap(bboxOtherList[0], bboxOtherList[2], bboxValueList[0], bboxValueList[2])

                    if bboxOtherList[1] >= bboxValueList[3] - height * self.levelMargin and bboxOtherList[1] - bboxValueList[3] <= height * self.levelUnitBelow and overlap >= min(bboxOtherList[2] - bboxOtherList[0], bboxValueList[2] - bboxValueList[0]) * self.levelColumnOverlap:
                        isHeader = True

                        break

                if isHeader == False:
                    labelList.append(labelObject)

            if len(labelList) < 2:
                continue

            charList = []

            for b in range(len(valueObject.get("partList", [valueObject]))):
                charList = charList + self._charPosition(valueObject.get("partList", [valueObject])[b])

            digitList = []

            for b in range(len(charList)):
                if len(charList[b]["text"].strip()) > 0:
                    digitList.append(charList[b])

            if len(digitList) == 0:
                continue

            tokenList = []

            for b in range(len(digitList)):
                tokenList.append({"text": digitList[b]["text"], "order": b * 2})

            for b in range(len(labelList)):
                bboxList = labelList[b]["bbox"]

                centerX = (bboxList[0] + bboxList[2]) / 2

                if centerX < digitList[0]["start"]:
                    tokenList.append({"text": labelList[b]["text"].strip(), "order": -1 + centerX / 100000})

                    continue

                indexBest = 0

                for c in range(len(digitList)):
                    if abs((digitList[c]["start"] + digitList[c]["end"]) / 2 - centerX) < abs((digitList[indexBest]["start"] + digitList[indexBest]["end"]) / 2 - centerX):
                        indexBest = c

                if centerX < digitList[indexBest]["start"]:
                    indexBest -= 1

                tokenList.append({"text": labelList[b]["text"].strip(), "order": indexBest * 2 + 1})

            tokenList.sort(key=lambda tokenObject: tokenObject["order"])

            textList = []

            for b in range(len(tokenList)):
                textList.append(tokenList[b]["text"])

            valueObject["text"] = "".join(textList)

            for b in range(len(labelList)):
                usedList.append(labelList[b])

        resultList = []

        for a in range(len(itemList)):
            if itemList[a] not in usedList:
                resultList.append(itemList[a])

        return resultList

    def _textPairBuild(self, restList, verticalList, height):
        pairList = []
        lineItemList = []

        pairItemList = []

        restList = self._verticalPair(restList, pairItemList, height) + pairItemList

        restList = self._letterLine(restList, height)

        restList = self._paragraphMerge(restList, height)

        bandList = self._bandBuild(restList)

        for a in range(len(bandList)):
            itemSortedList = sorted(bandList[a]["itemList"], key=lambda itemObject: itemObject["bbox"][0])

            columnList = []

            for b in range(len(itemSortedList)):
                bboxList = itemSortedList[b]["bbox"]

                isAdded = False

                for c in range(len(columnList)):
                    overlap = self._overlap(bboxList[0], bboxList[2], columnList[c]["x1"], columnList[c]["x2"])

                    if overlap < min(bboxList[2] - bboxList[0], columnList[c]["x2"] - columnList[c]["x1"]) * self.levelColumnOverlap:
                        continue

                    columnList[c]["x1"] = min(columnList[c]["x1"], bboxList[0])
                    columnList[c]["x2"] = max(columnList[c]["x2"], bboxList[2])
                    columnList[c]["itemList"].append(itemSortedList[b])

                    isAdded = True

                    break

                if isAdded == False:
                    columnList.append({"x1": bboxList[0], "x2": bboxList[2], "itemList": [itemSortedList[b]]})

            columnList.sort(key=lambda columnObject: columnObject["x1"])

            bboxBandList = bandList[a]["bbox"]

            segmentList = []

            for b in range(len(columnList)):
                if len(segmentList) > 0:
                    previousObject = segmentList[len(segmentList) - 1][len(segmentList[len(segmentList) - 1]) - 1]

                    isTitle = False

                    for c in range(len(verticalList)):
                        bboxTitleList = verticalList[c]["bbox"]

                        if bboxTitleList[0] >= previousObject["x2"] - height * self.levelMargin and bboxTitleList[2] <= columnList[b]["x1"] + height * self.levelMargin and self._overlap(bboxTitleList[1], bboxTitleList[3], bboxBandList[1], bboxBandList[3]) > 0:
                            isTitle = True

                            break

                    gapLimit = height * self.levelKeyGap if self._columnOption(columnList[b]) else height * self.levelFieldGap

                    if isTitle == False and columnList[b]["x1"] - previousObject["x2"] <= gapLimit:
                        segmentList[len(segmentList) - 1].append(columnList[b])

                        continue

                segmentList.append([columnList[b]])

            for b in range(len(segmentList)):
                self._optionSibling(segmentList[b])

            segmentList = self._optionSplit(segmentList)

            for b in range(len(segmentList)):
                segment = segmentList[b]

                isShort = True

                for c in range(len(segment)):
                    for d in range(len(segment[c]["itemList"])):
                        if len(self._textClean(segment[c]["itemList"][d]["text"])) > self.countUnitMaximum:
                            isShort = False

                keyText = self._textClean("".join(self._columnText(segment[0])))

                isSymbol = False

                for c in range(len(segment)):
                    if self._symbolCheck(self._textClean("".join(self._columnText(segment[c])))):
                        isSymbol = True

                if len(segment) < 2 or isShort or isSymbol or len(keyText) <= self.countUnitMaximum:
                    lineTextList = []

                    bboxLineList = None

                    for c in range(len(segment)):
                        columnItemList = sorted(segment[c]["itemList"], key=lambda itemObject: itemObject["bbox"][1])

                        for d in range(len(columnItemList)):
                            text = self._spaceNormalize(columnItemList[d]["text"])

                            lineTextList.append(f"{self.textMark} {text}" if columnItemList[d].get("isMark") else text)

                            bboxList = columnItemList[d]["bbox"]

                            bboxLineList = list(bboxList) if bboxLineList == None else [min(bboxLineList[0], bboxList[0]), min(bboxLineList[1], bboxList[1]), max(bboxLineList[2], bboxList[2]), max(bboxLineList[3], bboxList[3])]

                    lineItemList.append({"text": " ".join(lineTextList), "bbox": bboxLineList, "band": a})

                    continue

                textList = []

                bboxSegmentList = None

                for c in range(len(segment)):
                    columnItemList = sorted(segment[c]["itemList"], key=lambda itemObject: itemObject["bbox"][1])

                    partList = []

                    isMark = False

                    for d in range(len(columnItemList)):
                        partList.append(self._spaceNormalize(columnItemList[d]["text"]))

                        if columnItemList[d].get("isMark"):
                            isMark = True

                        bboxList = columnItemList[d]["bbox"]

                        bboxSegmentList = list(bboxList) if bboxSegmentList == None else [min(bboxSegmentList[0], bboxList[0]), min(bboxSegmentList[1], bboxList[1]), max(bboxSegmentList[2], bboxList[2]), max(bboxSegmentList[3], bboxList[3])]

                    textList.append(f"{self.textMark} {''.join(partList)}" if isMark else "".join(partList) if self._wideCheck((partList[0] or " ")[-1:] or " ") else " ".join(partList))

                sectionList = self._sectionCollect(bboxSegmentList, bboxSegmentList[0], verticalList, height)

                groupList = []

                for c in range(1, len(sectionList)):
                    groupList.append(sectionList[c]["text"])

                pairList.append({
                    "y": bboxSegmentList[1],
                    "section": sectionList[0]["text"] if len(sectionList) > 0 else "",
                    "group": " / ".join(groupList),
                    "sectionList": sectionList,
                    "row": "",
                    "key": textList[0],
                    "formula": "",
                    "value": " / ".join(textList[1:])
                })

        return {"pairList": pairList, "lineItemList": lineItemList}

    def _paragraphMerge(self, itemList, height):
        itemSortedList = sorted(itemList, key=lambda itemObject: itemObject["bbox"][1])

        resultList = []

        for a in range(len(itemSortedList)):
            itemObject = itemSortedList[a]

            bboxList = itemObject["bbox"]

            isMerged = False

            for b in range(len(resultList)):
                lastObject = resultList[b]

                bboxLastList = lastObject["lastBbox"]


                if self._overlap(bboxList[0], bboxList[2], bboxLastList[0], bboxLastList[2]) < min(bboxList[2] - bboxList[0], bboxLastList[2] - bboxLastList[0]) * self.levelParagraphOverlap:
                    continue

                widthRatio = min(bboxList[2] - bboxList[0], bboxLastList[2] - bboxLastList[0]) / max(bboxList[2] - bboxList[0], bboxLastList[2] - bboxLastList[0], 1)

                isAligned = abs(bboxList[0] - bboxLastList[0]) <= height * self.levelParagraphAlign or (abs((bboxList[0] + bboxList[2]) / 2 - (bboxLastList[0] + bboxLastList[2]) / 2) <= height * self.levelParagraphAlign and widthRatio >= self.levelParagraphWidth)

                if isAligned == False:
                    continue

                gap = bboxList[1] - bboxLastList[3]

                if gap < -min(bboxList[3] - bboxList[1], bboxLastList[3] - bboxLastList[1]) * self.levelParagraphOverlapLine or gap > height * self.levelLineGap:
                    continue

                if abs((bboxList[3] - bboxList[1]) - (bboxLastList[3] - bboxLastList[1])) > height * self.levelMargin * 2:
                    continue

                if itemObject.get("circleIndex", -1) < 0 and self._rowStructureCheck(bboxLastList, bboxList, itemSortedList, height):
                    continue

                lastObject["text"] = lastObject["text"] + ("" if self._wideCheck(lastObject["text"][-1:] or " ") else " ") + itemObject["text"]
                lastObject["bbox"] = [min(lastObject["bbox"][0], bboxList[0]), lastObject["bbox"][1], max(lastObject["bbox"][2], bboxList[2]), bboxList[3]]
                lastObject["lastBbox"] = bboxList
                lastObject["isMark"] = lastObject.get("isMark", False) or itemObject.get("isMark", False)
                lastObject["isOption"] = lastObject.get("isOption", False) or itemObject.get("isOption", False)

                isMerged = True

                break

            if isMerged == False:
                itemCopyObject = dict(itemObject)

                itemCopyObject["lastBbox"] = bboxList

                resultList.append(itemCopyObject)

        return resultList

    def _neighborFind(self, bboxList, itemList, height, isRight):
        resultObject = None
        gapBest = -1

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            if bboxOtherList == bboxList or self._rangeCheck(bboxOtherList, bboxList) == False:
                continue

            gap = bboxOtherList[0] - bboxList[2] if isRight else bboxList[0] - bboxOtherList[2]

            if gap < -height * self.levelMargin or gap > height * self.levelKeyGap:
                continue

            if gapBest < 0 or gap < gapBest:
                gapBest = gap
                resultObject = itemList[a]

        return resultObject

    def _rowStructureCheck(self, bboxFirstList, bboxSecondList, itemList, height):
        for a in range(2):
            isRight = a == 0

            firstObject = self._neighborFind(bboxFirstList, itemList, height, isRight)
            secondObject = self._neighborFind(bboxSecondList, itemList, height, isRight)

            if firstObject == None or secondObject == None:
                continue

            index = 0 if isRight else 2

            if firstObject is not secondObject and abs(firstObject["bbox"][index] - secondObject["bbox"][index]) <= height:
                return True

        return False

    def _optionSplit(self, segmentList):
        resultList = []

        for a in range(len(segmentList)):
            segment = segmentList[a]

            indexStart = 0

            b = 0

            while b < len(segment):
                isOption = self._columnOption(segment[b])

                if isOption == False or b == 0:
                    b += 1

                    continue

                indexKey = b - 1

                while indexKey > indexStart and self._columnOption(segment[indexKey]):
                    indexKey -= 1

                indexEnd = b

                while indexEnd + 1 < len(segment) and self._columnOption(segment[indexEnd + 1]):
                    indexEnd += 1

                if indexKey > indexStart:
                    resultList.append(segment[indexStart:indexKey])

                resultList.append(segment[indexKey:indexEnd + 1])

                indexStart = indexEnd + 1

                b = indexEnd + 1

            if indexStart < len(segment):
                resultList.append(segment[indexStart:])

        return resultList

    def _columnText(self, columnObject):
        textList = []

        for a in range(len(columnObject["itemList"])):
            textList.append(columnObject["itemList"][a]["text"])

        return textList

    def _optionSibling(self, segment):
        for a in range(len(segment)):
            isMark = False

            for b in range(len(segment[a]["itemList"])):
                if segment[a]["itemList"][b].get("isMark"):
                    isMark = True

            if isMark == False:
                continue

            for b in [-1, 1]:
                index = a + b

                widthMark = segment[a]["x2"] - segment[a]["x1"]

                while index > 0 and index < len(segment):
                    width = segment[index]["x2"] - segment[index]["x1"]

                    if width < widthMark * self.levelSiblingWidth or width > widthMark / self.levelSiblingWidth:
                        break

                    segment[index]["isSibling"] = True

                    index += b

    def _columnOption(self, columnObject):
        if columnObject.get("isSibling"):
            return True

        for a in range(len(columnObject["itemList"])):
            if columnObject["itemList"][a].get("isOption"):
                return True

        return False

    def _valueFilter(self, itemList):
        valueList = []

        for a in range(len(itemList)):
            if itemList[a]["type"] == "value":
                valueList.append(itemList[a])

        if len(valueList) == 0:
            return

        heightMinimum = self._heightMedian(valueList) * self.levelValueHeight

        for a in range(len(valueList)):
            if valueList[a]["bbox"][3] - valueList[a]["bbox"][1] < heightMinimum:
                valueList[a]["type"] = "formula"

    def _rowAnchor(self, itemObject, rowList, edgeRight):
        bboxList = itemObject["bbox"]

        centerY = (bboxList[1] + bboxList[3]) / 2

        result = None
        distanceBest = -1

        for a in range(len(rowList)):
            bboxRowList = rowList[a]["bbox"]

            if (bboxRowList[0] + bboxRowList[2]) / 2 < bboxList[2] or bboxRowList[2] > edgeRight:
                continue

            distance = abs((bboxRowList[1] + bboxRowList[3]) / 2 - centerY)

            if distanceBest < 0 or distance < distanceBest:
                distanceBest = distance
                result = rowList[a]

        return result

    def _captionCheck(self, bboxList, bboxAnchorList, verticalList, height):
        if bboxList[3] > (bboxAnchorList[1] + bboxAnchorList[3]) / 2 or bboxList[3] - bboxList[1] > (bboxAnchorList[3] - bboxAnchorList[1]) * (1 - self.levelCellSize):
            return False

        bboxSpanList = [0, min(bboxList[1], bboxAnchorList[1]), 0, max(bboxList[3], bboxAnchorList[3])]

        if self._wallCheck(verticalList, -1, bboxList[0] + height * self.levelMargin, bboxSpanList) == False:
            return False

        return self._wallCheck(verticalList, bboxList[2] - height * self.levelMargin, bboxAnchorList[0] + height * self.levelMargin, bboxSpanList) == False

    def _dashCellCheck(self, lineObject, bboxList, height):
        verticalList = lineObject["verticalList"]

        left = None
        right = None

        for a in range(len(verticalList)):
            bboxLineList = verticalList[a]

            if self._overlap(bboxLineList[1], bboxLineList[3], bboxList[1], bboxList[3]) < (bboxList[3] - bboxList[1]) * self.levelLineCover:
                continue

            if bboxLineList[2] <= bboxList[0] + height * self.levelMargin and (left == None or bboxLineList[2] > left):
                left = bboxLineList[2]

            if bboxLineList[0] >= bboxList[2] - height * self.levelMargin and (right == None or bboxLineList[0] < right):
                right = bboxLineList[0]

        if left == None or right == None:
            return False

        for a in range(len(lineObject["dashList"])):
            bboxDashList = lineObject["dashList"][a]

            if bboxDashList[0] > left and bboxDashList[2] < right and self._overlap(bboxDashList[1], bboxDashList[3], bboxList[1], bboxList[3]) >= (bboxList[3] - bboxList[1]) * self.levelLineCover:
                return True

        return False

    def _keyCollect(self, anchorObject, itemList, lineObject, height):
        bboxAnchorList = anchorObject["bbox"]

        candidateList = []

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            if itemList[a] is anchorObject or (bboxList[0] + bboxList[2]) / 2 > bboxAnchorList[0]:
                continue

            if self._sameRowCheck(itemList[a], anchorObject, itemList, lineObject, height) == False:
                continue

            if itemList[a]["type"] != "value" and (self._captionCheck(bboxList, bboxAnchorList, lineObject["verticalList"], height) or self._dashCellCheck(lineObject, bboxList, height)):
                continue

            candidateList.append(itemList[a])

        candidateList.sort(key=lambda itemObject: -itemObject["bbox"][2])

        resultList = []

        edgeLeft = None

        for a in range(len(candidateList)):
            itemObject = candidateList[a]

            if itemObject["type"] == "value":
                if self._rangeCheck(itemObject["bbox"], bboxAnchorList) == False:
                    continue

                break

            if itemObject["type"] == "row" and (anchorObject["type"] == "row" or self._rowFind(resultList, anchorObject) != None):
                break

            if edgeLeft != None and edgeLeft - itemObject["bbox"][2] > height * self.levelKeyReach:
                if itemObject["type"] not in ["key", "formula"] or self._wallCount(lineObject["verticalList"], itemObject["bbox"][2] + height * self.levelMargin, edgeLeft - height * self.levelMargin, itemObject["bbox"]) != 1:
                    break

            resultList.append(itemObject)

            edgeLeft = itemObject["bbox"][0] if edgeLeft == None else min(edgeLeft, itemObject["bbox"][0])

        return resultList

    def _leftCheck(self, itemObject, keyList, itemList, height):
        bboxList = itemObject["bbox"]

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            if itemList[a] is itemObject or itemList[a]["type"] not in ["key", "formula"] or bboxOtherList[2] > bboxList[0] + height * self.levelMargin:
                continue

            if bboxList[0] - bboxOtherList[2] > height * self.levelKeyGap:
                continue

            if self._rangeCheck(bboxOtherList, bboxList) == False:
                continue

            if itemList[a] not in keyList:
                return False

        return True

    def _keyExtend(self, keyList, itemList, bboxAnchorList, height, horizontalList, rowList, edgeRight, rowObject):
        resultList = list(keyList)

        isAdded = True

        while isAdded:
            isAdded = False

            for a in range(len(itemList)):
                itemObject = itemList[a]

                if itemObject["type"] not in ["key", "formula"] or itemObject in resultList:
                    continue

                bboxList = itemObject["bbox"]

                if self._overlap(bboxList[0], bboxList[2], bboxAnchorList[0], bboxAnchorList[2]) > 0:
                    continue

                isNear = False

                for b in range(len(resultList)):
                    bboxKeyList = resultList[b]["bbox"]

                    if resultList[b]["type"] not in ["key", "formula"]:
                        continue

                    if self._overlap(bboxList[0], bboxList[2], bboxKeyList[0], bboxKeyList[2]) <= 0:
                        continue

                    gap = max(bboxList[1] - bboxKeyList[3], bboxKeyList[1] - bboxList[3])

                    if gap > height * self.levelLineGap:
                        continue

                    if bboxList[1] < bboxKeyList[1] and self._ruleBetweenCheck(horizontalList, bboxList, bboxKeyList):
                        continue

                    if bboxList[1] > bboxKeyList[1] and self._ruleBetweenCheck(horizontalList, bboxKeyList, bboxList):
                        continue

                    isNear = True

                    break

                if isNear == False:
                    continue

                if self._leftCheck(itemObject, resultList, itemList, height) == False:
                    continue

                rowAnchorObject = self._rowAnchor(itemObject, rowList, edgeRight)

                if rowObject != None and rowAnchorObject != None and rowAnchorObject is not rowObject:
                    continue

                resultList.append(itemObject)

                isAdded = True

        return resultList

    def _sectionCollect(self, bboxAnchorList, keyLeft, verticalList, height):
        centerY = (bboxAnchorList[1] + bboxAnchorList[3]) / 2

        columnList = []

        for a in range(len(verticalList)):
            bboxList = verticalList[a]["bbox"]

            if bboxList[2] > keyLeft + height * self.levelMargin or keyLeft - bboxList[0] > height * self.levelSection:
                continue

            centerX = (bboxList[0] + bboxList[2]) / 2

            isAdded = False

            for b in range(len(columnList)):
                if abs(columnList[b]["centerX"] - centerX) <= height * self.levelRowColumn:
                    columnList[b]["itemList"].append(verticalList[a])

                    isAdded = True

                    break

            if isAdded == False:
                columnList.append({"centerX": centerX, "itemList": [verticalList[a]]})

        sectionList = []

        for a in range(len(columnList)):
            nearestObject = None
            distanceBest = -1
            isNearestAbove = False

            for b in range(len(columnList[a]["itemList"])):
                itemObject = columnList[a]["itemList"][b]

                bboxList = itemObject["bbox"]

                distance = max(bboxList[1] - centerY, centerY - bboxList[3], 0)

                if distance == 0:
                    nearestObject = itemObject

                    break

                if distance > height * self.levelSectionGap or bboxList[3] - bboxList[1] < height * self.levelSectionSpan:
                    continue

                isAbove = bboxList[3] < centerY

                if nearestObject == None or (isAbove and isNearestAbove == False) or (isAbove == isNearestAbove and distance < distanceBest):
                    distanceBest = distance
                    nearestObject = itemObject
                    isNearestAbove = isAbove

            if nearestObject != None:
                sectionList.append(nearestObject)

        sectionList.sort(key=lambda itemObject: itemObject["bbox"][0])

        return sectionList

    def _stackCheck(self, itemList, bboxList):
        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            if self._overlap(bboxOtherList[0], bboxOtherList[2], bboxList[0], bboxList[2]) > min(bboxOtherList[2] - bboxOtherList[0], bboxList[2] - bboxList[0]) * self.levelColumnOverlap:
                return True

        return False

    def _keyOrder(self, keyList, keyLeft, height):
        keySortedList = sorted(keyList, key=lambda itemObject: (int((itemObject["bbox"][0] - keyLeft) / (height * self.levelColumn)), itemObject["bbox"][1]))

        lineList = []

        for a in range(len(keySortedList)):
            column = int((keySortedList[a]["bbox"][0] - keyLeft) / (height * self.levelColumn))

            if len(lineList) > 0 and lineList[len(lineList) - 1]["column"] == column and self._rangeCheck(lineList[len(lineList) - 1]["bbox"], keySortedList[a]["bbox"]) and self._stackCheck(lineList[len(lineList) - 1]["itemList"], keySortedList[a]["bbox"]) == False:
                lineList[len(lineList) - 1]["itemList"].append(keySortedList[a])
                lineList[len(lineList) - 1]["bbox"] = self._bboxExpand(lineList[len(lineList) - 1]["bbox"], keySortedList[a]["bbox"])

                continue

            lineList.append({"column": column, "bbox": list(keySortedList[a]["bbox"]), "itemList": [keySortedList[a]]})

        resultList = []

        for a in range(len(lineList)):
            resultList = resultList + sorted(lineList[a]["itemList"], key=lambda itemObject: itemObject["bbox"][0])

        return resultList

    def _digitSpaceCheck(self, text):
        for a in range(len(text)):
            if unicodedata.category(text[a]) not in ["Nd", "Zs"]:
                return False

        return len(text) > 0

    def _pairBuild(self, anchorObject, keyList, verticalList, height):
        rowTextList = []
        formulaList = []
        textList = []

        keyLeft = anchorObject["bbox"][0]

        for a in range(len(keyList)):
            keyLeft = min(keyLeft, keyList[a]["bbox"][0])

        keySortedList = self._keyOrder(keyList, keyLeft, height)

        for a in range(len(keySortedList)):
            itemObject = keySortedList[a]

            if itemObject["type"] == "row":
                rowTextList.append(itemObject["text"].strip())
            elif itemObject["type"] == "formula":
                formulaList.append(itemObject["text"].strip())
            else:
                textList.append(itemObject["text"].strip())

        value = ""

        if anchorObject["type"] == "value":
            value = anchorObject["text"].strip()

            if self._digitSpaceCheck(value):
                value = self._textClean(value)

            if "suffix" in anchorObject:
                value = f"{value} {anchorObject['suffix']}"
        else:
            rowTextList.append(anchorObject["text"].strip())

        sectionList = self._sectionCollect(anchorObject["bbox"], keyLeft, verticalList, height)

        groupList = []

        for a in range(1, len(sectionList)):
            groupList.append(sectionList[a]["text"])

        return {
            "anchor": anchorObject,
            "keyList": keyList,
            "y": anchorObject["bbox"][1],
            "section": sectionList[0]["text"] if len(sectionList) > 0 else "",
            "group": " / ".join(groupList),
            "sectionList": sectionList,
            "row": " ".join(rowTextList),
            "key": " ".join(textList),
            "formula": " ".join(formulaList),
            "value": value
        }

    def _bandPairFind(self, anchorObject, pairList, height, horizontalList):
        bboxList = anchorObject["bbox"]

        centerY = (bboxList[1] + bboxList[3]) / 2

        resultObject = None
        rowRight = None

        for a in range(len(pairList)):
            pairObject = pairList[a]

            rowObject = self._rowFind(pairObject["keyList"], pairObject["anchor"])

            if rowObject == None or rowObject["bbox"][2] > bboxList[0] + height * self.levelMargin:
                continue

            if pairObject["anchor"]["type"] == "value" and self._overlap(pairObject["anchor"]["bbox"][0], pairObject["anchor"]["bbox"][2], bboxList[0], bboxList[2]) <= 0:
                continue

            bandList = self._bandFind(rowObject["bbox"], horizontalList)

            if bandList == None or centerY < bandList[0] or centerY > bandList[1]:
                continue

            if rowRight == None or rowObject["bbox"][2] > rowRight:
                rowRight = rowObject["bbox"][2]
                resultObject = pairObject

        return resultObject

    def _columnValueMerge(self, pairList, itemList, height, horizontalList):
        pairSortedList = sorted(pairList, key=lambda pairObject: pairObject["anchor"]["bbox"][0])

        targetList = []
        mergedList = []

        for a in range(len(pairSortedList)):
            pairObject = pairSortedList[a]

            anchorObject = pairObject["anchor"]

            targetList.append(pairObject)

            if anchorObject["type"] != "value" or pairObject["key"] != "" or pairObject["row"] != "" or pairObject["formula"] != "" or self._bareNumberCheck(self._textClean(anchorObject["text"])) == False:
                continue

            leftObject = None

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                centerY = (anchorObject["bbox"][1] + anchorObject["bbox"][3]) / 2

                if itemList[b] is anchorObject or bboxList[2] > anchorObject["bbox"][0] + height * self.levelMargin or bboxList[1] > centerY or bboxList[3] < centerY:
                    continue

                if leftObject == None or bboxList[2] > leftObject["bbox"][2]:
                    leftObject = itemList[b]

            if leftObject == None:
                bandObject = self._bandPairFind(anchorObject, pairList, height, horizontalList)

                if bandObject == None:
                    continue

                if bandObject["value"] == "":
                    bandObject["value"] = pairObject["value"]
                elif bandObject["anchor"]["bbox"][1] > anchorObject["bbox"][1]:
                    bandObject["value"] = f"{pairObject['value']} / {bandObject['value']}"
                else:
                    bandObject["value"] = f"{bandObject['value']} / {pairObject['value']}"

                mergedList.append(pairObject)

                continue

            if leftObject["type"] != "value":
                continue

            for b in range(a):
                if pairSortedList[b]["anchor"] is leftObject:
                    targetObject = targetList[b]

                    targetObject["value"] = f"{targetObject['value']} / {pairObject['value']}"

                    targetList[a] = targetObject

                    mergedList.append(pairObject)

                    break

        resultList = []

        for a in range(len(pairList)):
            isMerged = False

            for b in range(len(mergedList)):
                if pairList[a] is mergedList[b]:
                    isMerged = True

            if isMerged == False:
                resultList.append(pairList[a])

        return resultList

    def _rowFind(self, keyList, anchorObject):
        if anchorObject["type"] == "row":
            return anchorObject

        for a in range(len(keyList)):
            if keyList[a]["type"] == "row":
                return keyList[a]

        return None

    def _pairOrder(self, pairList):
        rowPairList = []
        otherPairList = []

        for a in range(len(pairList)):
            if pairList[a]["row"] != "" and self._numberValue(self._textClean(pairList[a]["row"])) >= 0:
                rowPairList.append(pairList[a])
            else:
                otherPairList.append(pairList[a])

        rowPairList.sort(key=lambda pairObject: self._numberValue(self._textClean(pairObject["row"])))
        otherPairList.sort(key=lambda pairObject: pairObject["y"])

        if len(rowPairList) == 0:
            return otherPairList

        yStart = rowPairList[0]["y"]

        beforeList = []
        afterList = []

        for a in range(len(otherPairList)):
            if otherPairList[a]["y"] < yStart:
                beforeList.append(otherPairList[a])
            else:
                afterList.append(otherPairList[a])

        return self._sectionContiguous(beforeList) + rowPairList + self._sectionContiguous(afterList)

    def _sectionContiguous(self, pairList):
        orderList = []

        for a in range(len(pairList)):
            if pairList[a]["section"] not in orderList:
                orderList.append(pairList[a]["section"])

        return sorted(pairList, key=lambda pairObject: orderList.index(pairObject["section"]))

    def _cellEscape(self, text):
        return text.replace("|", "\\|")

    def execute(self, itemPageList, ringList, lineObject, numberPage):
        itemPageList = self._ringArtifactRemove(itemPageList, ringList)

        self._enclosedMark(itemPageList, ringList)

        itemPageList = self._overlayJoin(itemPageList)

        itemPageList = self._gapInsert(itemPageList)

        self._markApply(itemPageList, ringList)

        self._optionApply(itemPageList, [])

        verticalBoxList = []

        itemPageList = self._verticalBoxCollect(itemPageList, verticalBoxList)

        mergeObject = self._verticalMerge(itemPageList, lineObject["horizontalList"])

        mergeObject["itemList"] = self._arcFit(mergeObject["itemList"], self._heightMedian(mergeObject["itemList"]))

        mergeObject["itemList"] = self._cellMerge(mergeObject["itemList"], lineObject, self._heightMedian(mergeObject["itemList"]))

        mergeObject["verticalList"] = mergeObject["verticalList"] + verticalBoxList

        heightPage = self._heightMedian(mergeObject["itemList"])

        mergeObject["itemList"] = self._letterMerge(mergeObject["itemList"], heightPage)


        self._optionApply(mergeObject["itemList"], [])


        mergeObject["verticalList"] = self._titleJoin(mergeObject["verticalList"], heightPage)

        itemList = []

        for a in range(len(mergeObject["itemList"])):
            itemList.append(dict(mergeObject["itemList"][a]))

        itemList.sort(key=lambda itemObject: (itemObject["bbox"][1], itemObject["bbox"][0]))

        height = self._heightMedian(itemList)

        itemList = self._formulaSplit(itemList)

        self._typeAssign(itemList)

        self._formulaContinue(itemList, height, lineObject)

        itemList = self._valueCompose(itemList, lineObject["verticalList"], height)

        self._rowDetect(itemList, height)

        self._valueFilter(itemList)

        itemList = self._unitAbove(itemList, height)

        rowList = []

        for a in range(len(itemList)):
            if itemList[a]["type"] == "row":
                rowList.append(itemList[a])

        pairList = []

        usedList = []

        anchorList = []

        for a in range(len(itemList)):
            if itemList[a]["type"] == "value":
                anchorList.append(itemList[a])

        for a in range(len(rowList)):
            anchorList.append(rowList[a])

        for a in range(len(anchorList)):
            anchorObject = anchorList[a]

            if anchorObject["type"] == "row" and anchorObject in usedList:
                continue

            keyList = self._keyCollect(anchorObject, itemList, lineObject, height)

            rowObject = self._rowFind(keyList, anchorObject)

            keyList = self._keyExtend(keyList, itemList, anchorObject["bbox"], height, lineObject["horizontalList"], rowList, anchorObject["bbox"][2], rowObject)

            pairList.append(self._pairBuild(anchorObject, keyList, mergeObject["verticalList"], height))

            usedList.append(anchorObject)

            for b in range(len(keyList)):
                usedList.append(keyList[b])

        pairList = self._columnValueMerge(pairList, itemList, height, lineObject["horizontalList"])

        pairList = self._pairOrder(pairList)

        sectionUsedList = []

        for a in range(len(pairList)):
            for b in range(len(pairList[a]["sectionList"])):
                if pairList[a]["sectionList"][b] not in sectionUsedList:
                    sectionUsedList.append(pairList[a]["sectionList"][b])

        restList = []

        for a in range(len(itemList)):
            if itemList[a] not in usedList:
                restList.append({"text": self._spaceNormalize(itemList[a]["text"]), "bbox": itemList[a]["bbox"], "page": numberPage, "isMark": itemList[a].get("isMark", False), "isOption": itemList[a].get("isOption", False), "circleIndex": itemList[a].get("circleIndex", -1)})

        textPairObject = self._textPairBuild(restList, mergeObject["verticalList"], height)

        pairList = self._pairOrder(pairList + textPairObject["pairList"])

        for a in range(len(textPairObject["pairList"])):
            for b in range(len(textPairObject["pairList"][a]["sectionList"])):
                if textPairObject["pairList"][a]["sectionList"][b] not in sectionUsedList:
                    sectionUsedList.append(textPairObject["pairList"][a]["sectionList"][b])

        restList = []

        bandObject = {}

        for a in range(len(textPairObject["lineItemList"])):
            lineObject = textPairObject["lineItemList"][a]

            if lineObject["band"] not in bandObject:
                bandObject[lineObject["band"]] = []

            bandObject[lineObject["band"]].append(lineObject)

        for band in bandObject:
            segmentLineList = sorted(bandObject[band], key=lambda lineObject: lineObject["bbox"][0])

            groupList = []

            for a in range(len(segmentLineList)):
                bboxList = segmentLineList[a]["bbox"]

                if len(groupList) > 0:
                    lastObject = groupList[len(groupList) - 1]

                    isTitle = False

                    for b in range(len(mergeObject["verticalList"])):
                        bboxTitleList = mergeObject["verticalList"][b]["bbox"]

                        if bboxTitleList[0] >= lastObject["bbox"][2] - height * self.levelMargin and bboxTitleList[2] <= bboxList[0] + height * self.levelMargin and self._overlap(bboxTitleList[1], bboxTitleList[3], bboxList[1], bboxList[3]) > 0:
                            isTitle = True

                            break

                    if isTitle == False and bboxList[0] - lastObject["bbox"][2] <= height * self.levelLineJoin:
                        lastObject["textList"].append(segmentLineList[a]["text"])
                        lastObject["bbox"] = [lastObject["bbox"][0], min(lastObject["bbox"][1], bboxList[1]), bboxList[2], max(lastObject["bbox"][3], bboxList[3])]

                        continue

                groupList.append({"textList": [segmentLineList[a]["text"]], "bbox": list(bboxList)})

            for a in range(len(groupList)):
                restList.append({"text": " | ".join(groupList[a]["textList"]), "bbox": groupList[a]["bbox"]})

        for a in range(len(mergeObject["verticalList"])):
            if mergeObject["verticalList"][a] not in sectionUsedList:
                restList.append({"text": mergeObject["verticalList"][a]["text"], "bbox": mergeObject["verticalList"][a]["bbox"], "page": numberPage})

        lineList = []

        sectionPrevious = None
        groupPrevious = None

        for a in range(len(pairList)):
            pairObject = pairList[a]

            if pairObject["section"] != sectionPrevious:
                if a > 0:
                    lineList.append("")

                if pairObject["section"] != "":
                    lineList = lineList + [f"### {pairObject['section']}", ""]

                lineList = lineList + ["| group | row | key | formula | value |", "| --- | --- | --- | --- | --- |"]

                sectionPrevious = pairObject["section"]
                groupPrevious = None

            group = pairObject["group"] if groupPrevious == None or groupPrevious.startswith(pairObject["group"]) == False else ""

            groupPrevious = pairObject["group"]

            lineList.append(f"| {self._cellEscape(group)} | {pairObject['row']} | {self._cellEscape(self._spaceNormalize(pairObject['key']))} | {self._cellEscape(self._spaceNormalize(pairObject['formula']))} | {self._cellEscape(self._spaceNormalize(pairObject['value']))} |")

        restList.sort(key=lambda itemObject: (int(itemObject["bbox"][1] / (height * self.levelLineBucket)), itemObject["bbox"][0]))

        lineList.append("")

        for a in range(len(restList)):
            lineList.append(f"- {restList[a]['text']}")

        return "\n".join(lineList)

    def itemPdfBuild(self, elementList, scale, numberPage):
        textList = []

        for a in range(len(elementList)):
            if elementList[a]["type"] != "text":
                continue

            elementObject = dict(elementList[a])

            elementObject["bbox"] = [elementObject["x0"], elementObject["y0"], elementObject["x1"], elementObject["y1"]]

            textList.append(elementObject)

        mergeList = self._textMerge(self._duplicateRemove(textList))

        itemList = []

        for a in range(len(mergeList)):
            elementObject = mergeList[a]

            charList = []

            for b in range(len(elementObject["charList"])):
                charList.append({"text": elementObject["charList"][b]["text"], "start": elementObject["charList"][b]["start"] * scale, "end": elementObject["charList"][b]["end"] * scale})

            itemList.append({"text": elementObject["text"], "bbox": [elementObject["x0"] * scale, elementObject["y0"] * scale, elementObject["x1"] * scale, elementObject["y1"] * scale], "isVertical": elementObject["isVertical"], "charList": charList, "page": numberPage})

        return itemList

    def _detectionBboxList(self, detectionList):
        resultList = []

        for a in range(len(detectionList)):
            resultList.append(boxFromPointList(detectionList[a]["coordinate"]))

        return resultList

    def _gridOverlap(self, cellList):
        slotObject = {}

        for a in range(len(cellList)):
            for b in range(cellList[a]["rowIndex"], cellList[a]["rowIndex"] + cellList[a]["rowSpan"]):
                for c in range(cellList[a]["columnIndex"], cellList[a]["columnIndex"] + cellList[a]["columnSpan"]):
                    if (b, c) not in slotObject:
                        slotObject[(b, c)] = 0

                    slotObject[(b, c)] += 1

        if len(slotObject) == 0:
            return 0

        countMultiple = 0

        for slot in slotObject:
            if slotObject[slot] > 1:
                countMultiple += 1

        return countMultiple / len(slotObject)

    def pageCheck(self, tablePageList, areaPage, bboxList):
        areaTable = 0
        areaLargest = 0

        tableLargest = None

        for a in range(len(tablePageList)):
            coordinateList = tablePageList[a]["coordinate"]

            area = (coordinateList[2] - coordinateList[0]) * (coordinateList[3] - coordinateList[1])

            areaTable += area

            if area > areaLargest:
                areaLargest = area
                tableLargest = tablePageList[a]

        if tableLargest == None or areaTable < areaPage * self.levelFormArea:
            return False

        areaText = 0
        areaInside = 0

        for a in range(len(bboxList)):
            area = (bboxList[a][2] - bboxList[a][0]) * (bboxList[a][3] - bboxList[a][1])

            areaText += area

            for b in range(len(tablePageList)):
                if boxCenterInsideCheck(bboxList[a], tablePageList[b]["coordinate"]):
                    areaInside += area

                    break

        if areaText == 0 or areaInside < areaText * self.levelFormText:
            return False

        return self._gridOverlap(tableLargest["cellList"]) >= self.levelFormOverlap

    def pdfParse(self, pathInput, password):
        return PdfChar().execute(pathInput, password)

    def _narrowCheck(self, character):
        return unicodedata.east_asian_width(character) not in ["W", "F"] and unicodedata.category(character)[0] in ["N", "L"]

    def _emBoxBuild(self, itemList):
        for a in range(len(itemList)):
            if itemList[a]["isVertical"]:
                continue

            text = self._textClean(itemList[a]["text"])

            if len(text) == 0:
                continue

            countNarrow = 0

            for b in range(len(text)):
                if self._narrowCheck(text[b]):
                    countNarrow += 1

            bboxList = itemList[a]["bbox"]

            if countNarrow * 2 > len(text):
                size = (bboxList[3] - bboxList[1]) / self.levelEmNarrowInk

                itemList[a]["bbox"] = [bboxList[0], bboxList[1] - size * self.levelEmNarrowTop, bboxList[2], bboxList[3] + size * self.levelEmNarrowBottom]
            else:
                size = (bboxList[3] - bboxList[1]) / self.levelEmWideInk

                itemList[a]["bbox"] = [bboxList[0], bboxList[1] - size * self.levelEmWideTop, bboxList[2], bboxList[3] + size * self.levelEmWideBottom]

    def ringBuild(self, image, detectionList):
        return self._ringCollect(image, self._heightBoxMedian(self._detectionBboxList(detectionList)))

    def lineBuild(self, image, detectionList):
        return self._lineCollect(image, self._heightBoxMedian(self._detectionBboxList(detectionList)))

    def _overlapTrim(self, bboxList, bboxDetectionList):
        resultList = list(bboxList)

        centerY = (bboxList[1] + bboxList[3]) / 2

        for a in range(len(bboxDetectionList)):
            bboxOtherList = bboxDetectionList[a]

            centerX = (bboxOtherList[0] + bboxOtherList[2]) / 2

            if centerX < bboxList[0] or centerX > bboxList[2] or bboxOtherList[3] <= bboxList[1] or bboxOtherList[1] >= bboxList[3]:
                continue

            if bboxOtherList[2] - bboxOtherList[0] > (bboxList[2] - bboxList[0]) * self.levelTrimWidth or self._overlap(bboxOtherList[1], bboxOtherList[3], bboxList[1], bboxList[3]) < (bboxOtherList[3] - bboxOtherList[1]) * self.levelTrimOverlap:
                continue

            if bboxOtherList[3] < centerY:
                resultList[1] = max(resultList[1], bboxOtherList[3])

            if bboxOtherList[1] > centerY:
                resultList[3] = min(resultList[3], bboxOtherList[1])

        return resultList

    def itemImageBuild(self, image, detectionList, recognition, numberPage):
        bboxDetectionList = self._detectionBboxList(detectionList)

        height = self._heightBoxMedian(bboxDetectionList)

        lineObject = self._lineCollect(image, height)

        imageClean = self._dashErase(image, lineObject["dashList"])

        imageInk = imageInkBuild(imageClean)

        boxList = []

        for a in range(len(bboxDetectionList)):
            bboxList = bboxDetectionList[a]

            isVertical = bboxList[3] - bboxList[1] > (bboxList[2] - bboxList[0]) * self.levelVerticalAspect

            isContainer = False

            for b in range(len(bboxDetectionList)):
                bboxOtherList = bboxDetectionList[b]

                areaInside = max(0, min(bboxOtherList[2], bboxList[2]) - max(bboxOtherList[0], bboxList[0])) * max(0, min(bboxOtherList[3], bboxList[3]) - max(bboxOtherList[1], bboxList[1]))

                if b != a and areaInside >= (bboxOtherList[2] - bboxOtherList[0]) * (bboxOtherList[3] - bboxOtherList[1]) * self.levelContain:
                    isContainer = True

                    break

            lineList = [bboxList] if isVertical or isContainer else self._lineSplit(bboxList, imageInk, height)

            for b in range(len(lineList)):
                if isVertical == False:
                    lineList[b] = self._overlapTrim(lineList[b], bboxDetectionList)

                splitList = self._boxSplit(lineList[b], imageInk, isVertical, height)

                for c in range(len(splitList)):
                    boxList.append({"bbox": splitList[c]["bbox"], "bboxRecognize": splitList[c]["bboxRecognize"], "isVertical": isVertical})

        ringList = self._ringCollect(image, height)

        quadList = []

        for a in range(len(boxList)):
            bboxRecognizeList = boxList[a]["bboxRecognize"]

            quadList.append([[bboxRecognizeList[0], bboxRecognizeList[1]], [bboxRecognizeList[2], bboxRecognizeList[1]], [bboxRecognizeList[2], bboxRecognizeList[3]], [bboxRecognizeList[0], bboxRecognizeList[3]]])

        recognitionList = recognition.execute(quadList, imageClean)

        itemList = []

        for a in range(len(quadList)):
            text = recognitionList[a]["text"]

            if len(text.strip()) == 0:
                continue

            itemList.append({"text": text, "bbox": boxList[a]["bbox"], "isVertical": boxList[a]["isVertical"], "charList": [], "page": numberPage})

        itemList = self._ringInterior(itemList, ringList, imageClean, imageInk, recognition)

        self._emBoxBuild(itemList)

        return {"itemList": itemList, "ringList": ringList, "lineObject": lineObject}

    def __init__(self):
        self.levelFormArea = 0.6
        self.levelFormText = 0.9
        self.levelFormOverlap = 0.3
        self.levelLineExtend = 0.5
        self.levelLineDouble = 1.7
        self.levelLineMiddle = 0.3
        self.levelLineValley = 0.4
        self.levelContain = 0.9
        self.levelRuleLength = 1.5
        self.levelRuleThick = 0.25
        self.levelRuleAspect = 20
        self.levelRuleContrast = 10
        self.levelDashGap = 0.5
        self.levelDashMinimum = 0.15
        self.levelDashMaximum = 0.5
        self.levelDashUniform = 0.7
        self.levelDashSide = 0.2
        self.levelDashIsolated = 0.6
        self.levelDashPeriod = 0.25
        self.levelDashPartner = 0.5
        self.countDash = 3
        self.levelCellSize = 0.35
        self.levelLineReach = 1.0
        self.levelLetterSpace = 0.5
        self.levelGutterReach = 2.0
        self.levelGutterAlign = 0.5

        self.levelEmWideInk = 0.91
        self.levelEmWideTop = -0.065
        self.levelEmWideBottom = 0.175
        self.levelEmNarrowInk = 0.674
        self.levelEmNarrowTop = 0.077
        self.levelEmNarrowBottom = 0.258

        self.levelRowOverlap = 0.2
        self.levelRowColumn = 1.0
        self.levelLineGap = 0.35
        self.levelValueHeight = 0.6
        self.levelMargin = 0.15
        self.levelKeyGap = 3.0
        self.levelKeyReach = 5.0
        self.levelSection = 7.0
        self.levelColumn = 2.5
        self.levelComposeGap = 3.0
        self.levelDigitGap = 1.5
        self.levelUnitGap = 2.0
        self.levelSectionGap = 6.0
        self.levelSectionSpan = 3.0
        self.levelUnitAbove = 1.0
        self.levelUnitBelow = 3.0
        self.levelUnitPrefix = 2.0
        self.levelColumnOverlap = 0.3
        self.levelLetterMinimum = 0.5
        self.levelLetterGap = 4.0
        self.levelTitleOverlap = 0.8
        self.levelTitleGap = 0.5
        self.levelParagraphOverlap = 0.5
        self.levelParagraphAlign = 1.0
        self.levelFieldGap = 1.5
        self.levelVerticalPairGap = 1.2
        self.levelVerticalPairSize = 0.25
        self.levelLetterLine = 12.0
        self.levelRingArtifact = 0.7
        self.levelSiblingWidth = 0.5
        self.levelParagraphWidth = 0.6
        self.levelParagraphOverlapLine = 0.5
        self.levelArcNeighbor = 4.0
        self.levelArcRadiusMinimum = 0.5
        self.levelArcRadiusMaximum = 3.0
        self.levelArcResidual = 0.15
        self.levelArcUniform = 1.5
        self.levelArcInner = 0.6
        self.countArcMinimum = 5
        self.angleArcMinimum = 150
        self.levelInsertRoom = 0.5
        self.levelLineBucket = 1.0
        self.levelLineJoin = 5.0
        self.countUnitMaximum = 2
        self.textMark = "◯"
        self.countRowMinimum = 3
        self.countRowDigit = 3
        self.countRowMissing = 1
        self.levelRowSlot = 2.0
        self.countLetterSpace = 3
        self.countLabelMinimum = 2
        self.levelVerticalGap = 4.0
        self.levelVerticalSize = 0.25
        self.levelPitch = 0.25
        self.levelPitchRatio = 1.8
        self.levelGapOutlier = 3.0
        self.levelBandOverlap = 0.3
        self.levelBandHeight = 2.75
        self.levelBandItem = 1.5
        self.countVerticalMinimum = 3
        self.levelVerticalAspect = 2.0
        self.levelLineCover = 0.9
        self.levelLineWidth = 0.2
        self.levelEmpty = 0.0
        self.levelSplitGap = 0.5
        self.levelRingBlock = 1.0
        self.levelRingContrast = 15
        self.levelRingSizeMinimum = 0.8
        self.levelRingSizeMaximum = 3.0
        self.levelRingHole = 0.5
        self.levelRingSpread = 0.09
        self.levelRingInner = 0.65
        self.levelTrimGap = 0.15
        self.levelTrimWidth = 0.5
        self.levelTrimOverlap = 0.5
        self.levelDuplicate = 0.6
        self.levelSize = 0.3
        self.levelLine = 0.4
        self.levelOverlap = 0.3
        self.levelGap = 1.0
