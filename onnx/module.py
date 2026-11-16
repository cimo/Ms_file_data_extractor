import sys
import math
import unicodedata
import cv2
import numpy

sys.dont_write_bytecode = True

# Source
import pdf
import reference
from helper import boxFromPointList, imageInkBuild, boxCenterInsideCheck

class PdfChar(pdf.Pdf):
    levelSplit = 1.5
    levelSpace = 1.0
    levelSpaceWord = 0.5

    def spaceCheck(gap, gapMedian, size, spaceWidth, characterPrevious, characterNext):
        if unicodedata.east_asian_width(characterPrevious) in ["W", "F"] and unicodedata.east_asian_width(characterNext) in ["W", "F"]:
            return False

        if gap > size * PdfChar.levelSpace:
            return True

        if unicodedata.category(characterPrevious) == "Nd" and unicodedata.category(characterNext) == "Nd":
            return False

        return spaceWidth > 0 and gapMedian < spaceWidth * PdfChar.levelSpaceWord and gap > spaceWidth * PdfChar.levelSpaceWord

    def gapMedian(charList):
        gapList = []

        for a in range(1, len(charList)):
            gapList.append(charList[a]["start"] - charList[a - 1]["end"])

        gapList.sort()

        return gapList[int(len(gapList) / 2)] if len(gapList) > 0 else 0

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

        spaceAdvance = 0

        if font["byteLength"] == 1 and font["isVertical"] == False:
            spaceAdvance = pdf.Pdf._fontDecode(self, " ", font)["widthFractionList"][0] * self.fontSize * self.horizontalScale

        if self.textRender != 3 and self.textRender != 7:
            pieceList = []

            isSpace = False

            for a in range(len(charList)):
                if len(charList[a]["text"].strip()) == 0:
                    isSpace = True

                    continue

                charList[a]["isSpaceBefore"] = isSpace

                isSpace = False

                if len(pieceList) > 0 and charList[a]["start"] - pieceList[len(pieceList) - 1]["end"] <= self.fontSize * self.levelSplit:
                    pieceObject = pieceList[len(pieceList) - 1]

                    pieceObject["end"] = charList[a]["end"]
                    pieceObject["charList"].append(charList[a])

                    continue

                pieceList.append({"text": "", "start": charList[a]["start"], "end": charList[a]["end"], "charList": [charList[a]]})

            for a in range(len(pieceList)):
                pieceCharList = pieceList[a]["charList"]

                gapMedian = PdfChar.gapMedian(pieceCharList)

                for b in range(len(pieceCharList)):
                    if b > 0:
                        characterPrevious = pieceCharList[b - 1]["text"][-1]
                        characterNext = pieceCharList[b]["text"][0]

                        isNarrow = unicodedata.east_asian_width(characterPrevious) not in ["W", "F"] and unicodedata.east_asian_width(characterNext) not in ["W", "F"]

                        if (pieceCharList[b]["isSpaceBefore"] and isNarrow) or PdfChar.spaceCheck(pieceCharList[b]["start"] - pieceCharList[b - 1]["end"], gapMedian, self.fontSize, spaceAdvance, characterPrevious, characterNext):
                            pieceList[a]["text"] += " "

                    pieceList[a]["text"] += pieceCharList[b]["text"]

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
                    "fontName": font["baseFont"],
                    "fontSize": math.floor(deviceFontSize * 100 + 0.5) / 100,
                    "spaceWidth": spaceAdvance * deviceFontSize / self.fontSize if self.fontSize != 0 else 0,
                    "isVertical": font["isVertical"],
                    "color": self.fillColor
                })

        self.textMatrixList = self._matrixMultiply(self.textMatrixList, [1, 0, 0, 1, 0, -advance] if font["isVertical"] else [1, 0, 0, 1, advance, 0])

class Module:
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

                if isLine and isSize and currentObject["isVertical"] == elementObject["isVertical"] and currentObject.get("fieldIndex", 0) == elementObject.get("fieldIndex", 0) and gap >= -sizeCurrent * self.levelOverlap and gap <= sizeCurrent * self.levelGap:
                    currentObject["partList"].append({"text": elementObject["text"], "gap": gap})
                    currentObject["charList"] = currentObject["charList"] + elementObject["charList"]
                    currentObject["x0"] = min(currentObject["x0"], elementObject["x0"])
                    currentObject["y0"] = min(currentObject["y0"], elementObject["y0"])
                    currentObject["x1"] = max(currentObject["x1"], elementObject["x1"])
                    currentObject["y1"] = max(currentObject["y1"], elementObject["y1"])

                    isMerged = True

            if isMerged == False:
                resultObject = dict(elementObject)

                resultObject["partList"] = []

                resultList.append(resultObject)

        for a in range(len(resultList)):
            resultObject = resultList[a]

            gapMedian = PdfChar.gapMedian(resultObject["charList"]) if resultObject["isVertical"] == False else 0

            for b in range(len(resultObject["partList"])):
                partObject = resultObject["partList"][b]

                textCurrent = resultObject["text"]

                isSpace = len(textCurrent) > 0 and len(partObject["text"]) > 0 and PdfChar.spaceCheck(partObject["gap"], gapMedian, resultObject["fontSize"], resultObject.get("spaceWidth", 0), textCurrent[-1], partObject["text"][0])

                resultObject["text"] = f"{textCurrent} {partObject['text']}" if isSpace else f"{textCurrent}{partObject['text']}"

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

    def _lineRunCollect(self, isVertical, lineList, bboxPixelList):
        axis = 1 if isVertical else 0
        cross = 1 - axis

        resultList = []

        for a in range(len(lineList)):
            bboxLineList = lineList[a]

            if bboxLineList[axis] >= bboxPixelList[axis] and bboxLineList[axis + 2] <= bboxPixelList[axis + 2] and bboxLineList[cross] <= bboxPixelList[cross] and bboxLineList[cross + 2] >= bboxPixelList[cross + 2]:
                resultList.append([bboxLineList[axis] - bboxPixelList[axis], bboxLineList[axis + 2] - bboxPixelList[axis]])

        return resultList

    def _boxSplit(self, bboxList, imageInk, isVertical, height, lineList):
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

        if profileList.sum() == 0:
            return [{"bbox": list(bboxList), "bboxRecognize": list(bboxList)}]

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

        lineRunList = lineRunList + self._lineRunCollect(isVertical, lineList, [x1, y1, x2, y2])

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

                isInside = cropSegment.shape[1] <= height and runBest[1] - runBest[0] < cropSegment.shape[1] * self.levelStrokeFlat and rowRunList[b][0] > 0 and rowRunList[b][1] < len(rowProfileList)

                if rowRunList[b][1] <= crossStart and (isInside or crossStart - rowRunList[b][1] <= height * self.levelTrimGap):
                    crossStart = rowRunList[b][0]
                elif rowRunList[b][0] >= crossEnd and (isInside or rowRunList[b][0] - crossEnd <= height * self.levelTrimGap):
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

    def _fractionRuleFilter(self, height, horizontalList, verticalList):
        reach = height * self.levelRuleEnd

        resultList = []

        for a in range(len(horizontalList)):
            bboxList = horizontalList[a]

            isJoin = bboxList[2] - bboxList[0] >= height * self.levelRuleFraction

            for b in range(len(verticalList)):
                if verticalList[b][1] <= bboxList[3] + reach and verticalList[b][3] >= bboxList[1] - reach and verticalList[b][2] >= bboxList[0] - reach and verticalList[b][0] <= bboxList[2] + reach:
                    isJoin = True

            for b in range(len(horizontalList)):
                if b != a and abs((horizontalList[b][1] + horizontalList[b][3]) / 2 - (bboxList[1] + bboxList[3]) / 2) <= reach and horizontalList[b][0] <= bboxList[2] + reach and horizontalList[b][2] >= bboxList[0] - reach:
                    isJoin = True

            if isJoin:
                resultList.append(bboxList)

        return resultList

    def _shortRuleFilter(self, height, horizontalList, verticalList):
        reach = height * self.levelRuleEnd

        resultList = []

        for a in range(len(horizontalList)):
            bboxList = horizontalList[a]

            if bboxList[2] - bboxList[0] >= height * self.levelRuleLength:
                resultList.append(bboxList)

                continue

            isLeft = False
            isRight = False

            for b in range(len(verticalList)):
                if verticalList[b][1] > bboxList[3] + reach or verticalList[b][3] < bboxList[1] - reach:
                    continue

                if abs(verticalList[b][2] - bboxList[0]) <= reach:
                    isLeft = True

                if abs(verticalList[b][0] - bboxList[2]) <= reach:
                    isRight = True

            if isLeft and isRight:
                resultList.append(bboxList)

        return resultList

    def _shortWallCollect(self, imageInk, height, verticalList, horizontalList):
        imageVertical = cv2.morphologyEx(imageInk, cv2.MORPH_OPEN, numpy.ones((max(1, int(round(height * self.levelRuleLengthHorizontal))), 1), numpy.uint8))

        reach = height * self.levelRuleEnd

        resultList = []

        count, _, statList, _ = cv2.connectedComponentsWithStats(imageVertical)

        for a in range(1, count):
            x, y, width, heightLine = statList[a][0:4]

            if heightLine >= height * self.levelRuleLength or (width > height * self.levelRuleThick and heightLine < width * self.levelRuleAspect):
                continue

            isKnown = False

            for b in range(len(verticalList)):
                if verticalList[b][0] <= x + width and verticalList[b][2] >= x and verticalList[b][1] <= y + heightLine and verticalList[b][3] >= y:
                    isKnown = True

                    break

            if isKnown:
                continue

            isTop = False
            isBottom = False

            for b in range(len(horizontalList)):
                bboxList = horizontalList[b]

                if bboxList[2] - bboxList[0] < height * self.levelRuleLength or bboxList[0] > x + width + reach or bboxList[2] < x - reach:
                    continue

                if abs((bboxList[1] + bboxList[3]) / 2 - y) <= reach:
                    isTop = True

                if abs((bboxList[1] + bboxList[3]) / 2 - (y + heightLine)) <= reach:
                    isBottom = True

            if isTop and isBottom:
                resultList.append([int(x), int(y), int(x + width), int(y + heightLine)])

        return resultList

    def _lineCollect(self, image, height):
        imageInk = cv2.adaptiveThreshold(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 1, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, int(height) * 2 + 1, self.levelRuleContrast)

        imageVertical = cv2.morphologyEx(imageInk, cv2.MORPH_OPEN, numpy.ones((max(1, int(round(height * self.levelRuleLength))), 1), numpy.uint8))
        imageHorizontal = cv2.morphologyEx(imageInk, cv2.MORPH_OPEN, numpy.ones((1, max(1, int(round(height * self.levelRuleLengthHorizontal)))), numpy.uint8))

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

        resultObject["verticalList"] = resultObject["verticalList"] + self._shortWallCollect(imageInk, height, resultObject["verticalList"], resultObject["horizontalList"])

        resultObject["horizontalList"] = self._fractionRuleFilter(height, self._shortRuleFilter(height, resultObject["horizontalList"], resultObject["verticalList"]), resultObject["verticalList"])

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

    def _ruleCrossCheck(self, bboxList, bboxOtherList, horizontalList):
        if bboxList[1] + bboxList[3] <= bboxOtherList[1] + bboxOtherList[3]:
            return self._ruleBetweenCheck(horizontalList, bboxList, bboxOtherList)

        return self._ruleBetweenCheck(horizontalList, bboxOtherList, bboxList)

    def _sameRowCheck(self, itemObject, anchorObject, itemList, lineObject, height):
        bboxList = itemObject["bbox"]
        bboxAnchorList = anchorObject["bbox"]

        if self._rangeCheck(bboxList, bboxAnchorList) and self._ruleCrossCheck(bboxList, bboxAnchorList, lineObject["horizontalList"]) == False:
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

            if itemList[a] is itemObject or itemList[a] is anchorObject or ("detectionIndex" in itemObject and itemList[a].get("detectionIndex") == itemObject["detectionIndex"]):
                continue

            centerX = (bboxOtherList[0] + bboxOtherList[2]) / 2

            if centerX > bboxList[2] and centerX < bboxAnchorList[0] and self._rangeCheck(bboxOtherList, bboxList) and (anchorObject["type"] != "row" or self._wallCheck(lineObject["verticalList"], bboxList[2], centerX, bboxList)):
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

        resultObject = {"text": "".join(textList), "bbox": bboxList, "isVertical": False, "charList": charList, "page": runList[0].get("page", 1)}

        if "detectionIndex" in runList[0]:
            resultObject["detectionIndex"] = runList[0]["detectionIndex"]

        return resultObject

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

    def _numberSeparatorCheck(self, itemObject, itemOtherObject):
        text = self._textClean(itemObject["text"])
        textOther = self._textClean(itemOtherObject["text"])

        if len(text) < 2 or len(textOther) == 0 or unicodedata.category(text[-1]) != "Po" or unicodedata.category(text[0]) != "Nd" or unicodedata.category(textOther[0]) != "Nd":
            return False

        return self._letterContain(text) == False and self._letterContain(textOther) == False

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

            isSeparator = self._numberSeparatorCheck(runList[a - 1], runList[a]) and gap <= heightLocal * self.levelSeparatorGap

            if isSeparator:
                isJoin = True

            for b in [a - 1, a]:
                if isJoin and isSeparator == False and self._bareNumberCheck(self._textClean(runList[b]["text"])) and self._numberJoinCheck(runList, b) == False:
                    isJoin = False

            if isJoin and isSeparator == False and self._gutterCheck(itemList, runList, a, lineObject, height):
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

    def _captionGroupCheck(self, groupList, height):
        isToken = True
        isLetter = True

        for a in range(len(groupList)):
            bboxList = groupList[a]["bbox"]

            if bboxList[3] - bboxList[1] > height * self.levelUnitSize:
                return False

            if self.reference.captionCheck(groupList[a]["text"], self.reference.dateCaptionList) == False:
                isToken = False

            if self.reference.dateLetterCheck(groupList[a]["text"]) == False:
                isLetter = False

        return isToken or isLetter

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

                if self._wallCheck(lineList, bboxPreviousList[2] - height * self.levelMargin, max(bboxList[0] + height * self.levelMargin, (bboxList[0] + bboxList[2]) / 2), bboxLineList):
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

                    if (isCell == False and self._letterSpaceCheck(groupList[c]) == False) or self._captionGroupCheck(groupList[c], height):
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
        ringIndexList = []

        for a in range(len(contourList)):
            if hierarchy[0][a][3] >= 0:
                continue

            if self._ringSizeCheck(contourList[a], height) == False:
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
            ringIndexList.append(a)

        for a in range(len(contourList)):
            parent = hierarchy[0][a][3]

            if parent < 0 or parent in ringIndexList:
                continue

            if self._ringSizeCheck(contourList[a], height) == False:
                continue

            if self._ellipseSpread(contourList[a]) > self.levelRingSpread:
                continue

            (centerX, centerY), radius = cv2.minEnclosingCircle(contourList[a])

            radius += self._ringStroke(contourList[a], height, binary)

            ringList.append({"bbox": [float(centerX - radius), float(centerY - radius), float(centerX + radius), float(centerY + radius)]})

        return ringList

    def _ringSizeCheck(self, contour, height):
        x, y, width, heightContour = cv2.boundingRect(contour)

        if width < height * self.levelRingSizeMinimum or width > height * self.levelRingSizeMaximum:
            return False

        return heightContour >= height * self.levelRingSizeMinimum and heightContour <= height * self.levelRingSizeMaximum

    def _ringStroke(self, contour, height, binary):
        x, y, width, heightContour = cv2.boundingRect(contour)

        margin = int(height * self.levelRingStroke) + 1

        x0 = max(0, x - margin)
        y0 = max(0, y - margin)
        x1 = min(binary.shape[1], x + width + margin)
        y1 = min(binary.shape[0], y + heightContour + margin)

        imageMask = numpy.zeros((y1 - y0, x1 - x0), dtype=numpy.uint8)

        cv2.drawContours(imageMask, [contour - numpy.array([x0, y0])], -1, 255, -1)

        imageInk = binary[y0:y1, x0:x1]

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

        stroke = 1

        for a in range(margin):
            imageMaskNext = cv2.dilate(imageMask, kernel)

            bandList = (imageMaskNext > 0) & (imageMask == 0)

            if numpy.count_nonzero(bandList) == 0 or numpy.count_nonzero(imageInk[bandList]) < numpy.count_nonzero(bandList) * self.levelRingStrokeInk:
                break

            stroke += 1

            imageMask = imageMaskNext

        return stroke

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

    def _verticalMerge(self, itemList, lineObject):
        horizontalList = lineObject["horizontalList"]

        heightPage = self._heightMedian(itemList)

        candidateList = []
        otherList = []

        for a in range(len(itemList)):
            if self._verticalCandidateCheck(itemList[a]) and (len(itemList[a]["text"].strip()) != 1 or self._rowMarkerCheck(itemList[a], itemList, heightPage, lineObject) == False):
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

                edgeList.append({"ratio": ratio, "first": a, "second": b, "gap": max(bboxOtherList[0] - bboxList[2], bboxList[0] - bboxOtherList[2], 0)})

        edgeList.sort(key=lambda edgeObject: (edgeObject["gap"], -edgeObject["ratio"]))

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

    def _textAppend(self, text, textNext):
        textNext = self._spaceNormalize(textNext)

        if len(text) == 0 or len(textNext) == 0 or unicodedata.category(text[-1]) == "Zs" or (self._wideCheck(text[-1]) and self._wideCheck(textNext[0])):
            return f"{text}{textNext}"

        return f"{text} {textNext}"

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

        countWeight = 0

        while countLetter < len(text) and unicodedata.category(text[countLetter])[0] == "L":
            countWeight += self.countUnitMaximum + 1 if self._wideCheck(text[countLetter]) else 1

            countLetter += 1

        if countWeight > self.countUnitMaximum:
            return False

        isDigit = False

        for a in range(len(text)):
            if unicodedata.category(text[a]) in ["Nd", "No"]:
                isDigit = True

        for a in range(len(text)):
            if unicodedata.category(text[a]) == "Sm" and isDigit:
                return True

        if isDigit and unicodedata.category(text[-1]) == "Sm":
            return True

        if isDigit and self._letterContain(text) == False and self._formulaMarkContain(text):
            return True

        countLetterAll = 0
        countOpen = 0
        countClose = 0

        for a in range(len(text)):
            category = unicodedata.category(text[a])

            if category[0] == "L":
                countLetterAll += 1
            elif category == "Ps":
                countOpen += 1
            elif category == "Pe":
                countClose += 1

        return isDigit and countOpen > 0 and countOpen == countClose and countLetterAll <= self.countUnitMaximum and unicodedata.category(text[0]) == "Ps"

    def _ringNumberCheck(self, text):
        if len(text) < 2 or unicodedata.category(text[0]) != "No" or unicodedata.digit(text[0], -1) < 0:
            return False

        for a in range(1, len(text)):
            if unicodedata.category(text[a]) != "Nd":
                return False

        return True

    def _digitValue(self, text):
        digitText = ""

        if self._ringNumberCheck(text):
            digitText = str(unicodedata.digit(text[0]))

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

    def _formulaMarkContain(self, text):
        for a in range(len(text)):
            if unicodedata.category(text[a]) in ["Sm", "Pd"]:
                return True

        return False

    def _wallLongCheck(self, bboxList, lineList, start, end, height):
        centerY = (bboxList[1] + bboxList[3]) / 2

        for a in range(len(lineList)):
            if lineList[a][2] <= start or lineList[a][0] >= end or lineList[a][3] - lineList[a][1] < height * self.levelWallCutLength or lineList[a][2] - lineList[a][0] > height * self.levelLineWidth:
                continue

            if lineList[a][1] <= centerY and lineList[a][3] >= centerY:
                return True

        return False

    def _wallCutFind(self, charList, index, wallList, centerY, height):
        centerLeft = (charList[index - 1]["start"] + charList[index - 1]["end"]) / 2
        centerRight = (charList[index]["start"] + charList[index]["end"]) / 2

        for a in range(len(wallList)):
            if wallList[a][0] > centerLeft and wallList[a][2] < centerRight and wallList[a][1] <= centerY - height / 2 and wallList[a][3] >= centerY + height / 2:
                return wallList[a]

        return None

    def _itemWallSplit(self, itemList, verticalList):
        height = self._heightMedian(itemList)

        wallList = []

        for a in range(len(verticalList)):
            if verticalList[a][3] - verticalList[a][1] >= height * self.levelWallCutLength and verticalList[a][2] - verticalList[a][0] <= height * self.levelLineWidth:
                wallList.append(verticalList[a])

        resultList = []

        indexPart = 0

        for a in range(len(itemList)):
            itemObject = itemList[a]

            charList = itemObject["charList"] if len(itemObject["charList"]) > 0 else itemObject.get("charPositionList", [])

            text = ""

            for b in range(len(charList)):
                text += charList[b]["text"]

            if itemObject["isVertical"] or self._textClean(text) != self._textClean(itemObject["text"]) or self._letterContain(itemObject["text"]) == False:
                resultList.append(itemObject)

                continue

            bboxList = itemObject["bbox"]

            centerY = (bboxList[1] + bboxList[3]) / 2

            indexStart = 0

            left = bboxList[0]

            partList = []

            for b in range(1, len(charList) + 1):
                wallObject = None

                if b < len(charList):
                    wallObject = self._wallCutFind(charList, b, wallList, centerY, height)

                    if wallObject == None or self._letterContain(text[indexStart:b]) == False or self._letterContain(text[b:]) == False:
                        continue

                partObject = dict(itemObject)
                partObject["text"] = text[indexStart:b]
                partObject["charList"] = charList[indexStart:b] if len(itemObject["charList"]) > 0 else []
                partObject["charPositionList"] = charList[indexStart:b]
                partObject["bbox"] = [left, max(bboxList[1], centerY - height * self.levelWallCutHeight), bboxList[2] if b == len(charList) else wallObject[0], min(bboxList[3], centerY + height * self.levelWallCutHeight)]

                if len(partList) > 0 and "detectionIndex" in itemObject:
                    indexPart += 1

                    partObject["detectionIndex"] = -self.countPartIndex - indexPart

                partList.append(partObject)

                indexStart = b

                if wallObject != None:
                    left = wallObject[2]

            if len(partList) == 1:
                resultList.append(itemObject)
            else:
                resultList = resultList + partList

        return resultList

    def _bracketCount(self, text):
        count = 0

        for a in range(len(text)):
            category = unicodedata.category(text[a])

            if category == "Ps":
                count += 1
            elif category == "Pe":
                count -= 1

        return count

    def _bracketJoin(self, itemList, verticalList, height):
        itemSortedList = sorted(itemList, key=lambda itemObject: itemObject["bbox"][0])

        removeList = []

        for a in range(len(itemSortedList)):
            itemObject = itemSortedList[a]

            if itemObject in removeList or self._letterContain(itemObject["text"]) == False:
                continue

            count = self._bracketCount(itemObject["text"])

            if count <= 0:
                continue

            joinList = []

            for b in range(a + 1, len(itemSortedList)):
                bboxLastList = joinList[len(joinList) - 1]["bbox"] if len(joinList) > 0 else itemObject["bbox"]

                bboxOtherList = itemSortedList[b]["bbox"]

                if itemSortedList[b] in removeList or itemSortedList[b].get("isOption") or self._rangeCheck(bboxLastList, bboxOtherList) == False or bboxOtherList[0] < bboxLastList[2] - height * self.levelMargin:
                    continue

                if self._wallCheck(verticalList, bboxLastList[2] - height * self.levelMargin, bboxOtherList[0] + height * self.levelMargin, bboxOtherList):
                    break

                joinList.append(itemSortedList[b])

                count += self._bracketCount(itemSortedList[b]["text"])

                if count <= 0:
                    break

            if count != 0:
                continue

            for b in range(len(joinList)):
                itemObject["text"] = f"{itemObject['text']} {joinList[b]['text']}"
                itemObject["bbox"] = self._bboxExpand(itemObject["bbox"], joinList[b]["bbox"])

                removeList.append(joinList[b])

        resultList = []

        for a in range(len(itemList)):
            if itemList[a] not in removeList:
                resultList.append(itemList[a])

        return resultList

    def _enclosureRemove(self, itemList):
        resultList = []

        for a in range(len(itemList)):
            if itemList[a].get("isEnclosure") == None:
                resultList.append(itemList[a])

        return resultList

    def _numberRightCheck(self, bboxList, itemList, horizontalList):
        bandList = self._bandFind(bboxList, horizontalList)

        if bandList == None:
            return False

        for a in range(len(itemList)):
            text = self._textClean(itemList[a]["text"])

            bboxOtherList = itemList[a]["bbox"]

            centerY = (bboxOtherList[1] + bboxOtherList[3]) / 2

            if bboxOtherList[0] >= bboxList[2] and len(text) <= self.countRowDigit and self._numberValue(text) >= 0 and centerY >= bandList[0] and centerY <= bandList[1]:
                return True

        return False

    def _formulaSplit(self, itemList, horizontalList):
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

                if category in ["Nd", "No"] and countLetter > 0 and self._letterContain(text[b:]) == False and self._formulaMarkContain(text[b:]) and self._numberRightCheck(itemList[a]["bbox"], itemList, horizontalList):
                    indexSplit = b

                    break

                if category[0] == "L":
                    countLetter += self.countUnitMaximum + 1 if self._wideCheck(text[b]) else 1
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
            formulaObject["isFormula"] = True

            resultList.append(keyObject)
            resultList.append(formulaObject)

        return resultList

    def _numberCellCheck(self, text):
        return "|" in text and self._numberCheck(text.replace("|", ""))

    def _numberSuffixCheck(self, text):
        index = len(text)

        while index > 0 and unicodedata.category(text[index - 1])[0] == "L":
            index -= 1

        return index > 0 and index <= self.countRowDigit and len(text) - index > 0 and self._suffixUnitCheck(text[index:]) and self._numberCheck(text[0:index])

    def _numberUnitCheck(self, text):
        index = len(text)

        while index > 0 and unicodedata.category(text[index - 1])[0] == "L":
            index -= 1

        countDigit = 0

        for a in range(index):
            if unicodedata.category(text[a]) == "Nd":
                countDigit += 1

        return index > 0 and (index == len(text) or self._suffixUnitCheck(text[index:])) and countDigit > self.countRowDigit and self._numberCheck(text[0:index])

    def _typeAssign(self, itemList, height):
        for a in range(len(itemList)):
            text = self._textClean(itemList[a]["text"])

            if itemList[a].get("isFormula"):
                itemList[a]["type"] = "formula"
            elif itemList[a].get("fieldIndex", 0) != 0:
                itemList[a]["type"] = "value"
            elif self._zeroCheck(text):
                itemList[a]["type"] = "suffix"
            elif itemList[a]["bbox"][3] - itemList[a]["bbox"][1] <= height * self.levelDisplaySize and (self._numberCheck(text) or self._numberUnitCheck(text) or self._numberCellCheck(text)):
                itemList[a]["type"] = "value"
            elif len(text) > 0 and self._formulaCheck(text):
                itemList[a]["type"] = "formula"
            else:
                itemList[a]["type"] = "key"

    def _outsideMark(self, lineObject, itemList):
        horizontalList = lineObject["horizontalList"]

        widthMaximum = 0

        for a in range(len(horizontalList)):
            widthMaximum = max(widthMaximum, horizontalList[a][2] - horizontalList[a][0])

        top = None
        bottom = None

        for a in range(len(horizontalList)):
            if horizontalList[a][2] - horizontalList[a][0] >= widthMaximum * self.levelTableRule:
                top = horizontalList[a][1] if top == None else min(top, horizontalList[a][1])
                bottom = horizontalList[a][3] if bottom == None else max(bottom, horizontalList[a][3])

        if top == None:
            return

        for a in range(len(itemList)):
            centerY = (itemList[a]["bbox"][1] + itemList[a]["bbox"][3]) / 2

            if (centerY < top or centerY > bottom) and self._cellFind(itemList[a]["bbox"], lineObject) == None:
                itemList[a]["type"] = "key"
                itemList[a]["isOutside"] = True

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

            if self._ringNumberCheck(text) or (itemList[a].get("fieldIndex", 0) == 0 and itemList[a]["type"] in ["value", "formula"] and countDigit > 0 and countDigit <= self.countRowDigit and countDigit * 2 >= len(text)):
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

                if len(runList) >= self.countRowMinimum and len(columnItemList) >= self.countRowColumn:
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

    def _valueCompose(self, itemList, height, horizontalList, verticalList):
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

                    if self._rangeCheck(candidateObject["bbox"], lastObject["bbox"]) == False or self._ruleBetweenCheck(horizontalList, lastObject["bbox"], candidateObject["bbox"]):
                        continue

                    if nextObject == None or candidateObject["bbox"][0] < nextObject["bbox"][0]:
                        nextObject = candidateObject

                if nextObject == None:
                    continue

                gap = nextObject["bbox"][0] - lastObject["bbox"][2]

                text = self._textClean(nextObject["text"])

                isNumber = nextObject["type"] in ["value", "suffix"]
                heightMaximum = max(nextObject["bbox"][3] - nextObject["bbox"][1], lastObject["bbox"][3] - lastObject["bbox"][1])

                isUnit = (self._numberSuffixCheck(text) or (len(text) > 0 and self._suffixUnitCheck(text) and self._bareNumberCheck(text) == False and lastObject["type"] in ["value", "suffix"])) and gap <= heightMaximum * self.levelUnitGap
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

                if self._wallLongCheck(bboxSpanList, verticalList, lastObject["bbox"][2] - height * self.levelMargin, nextObject["bbox"][0] + height * self.levelMargin, height):
                    continue

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

            resultObject = {"text": text, "bbox": bboxList, "type": "value", "page": chainList[0].get("page", 1), "partList": chainList}

            if "detectionIndex" in chainList[0]:
                resultObject["detectionIndex"] = chainList[0]["detectionIndex"]

            resultList.append(resultObject)

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
                if self._letterContain(enclosureObject["text"]) == False:
                    enclosureObject["isEnclosure"] = True

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

    def _ringTextCheck(self, text):
        if len(text) > self.countUnitMaximum:
            return False

        if len(text) == 1:
            return True

        for a in range(len(text)):
            if unicodedata.category(text[a]) == "Nd":
                return False

        return True

    def _ringArtifactRemove(self, itemList, ringList):
        resultList = []

        for a in range(len(itemList)):
            isArtifact = False

            if self._ringTextCheck(self._textClean(itemList[a]["text"])):
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

    def _stackLetterCheck(self, text):
        if len(text) == 0 or len(text) > self.countStackLetter:
            return False

        for a in range(len(text)):
            if unicodedata.category(text[a])[0] != "L":
                return False

        return True

    def _stackMemberCollect(self, itemObject, lineList, horizontalList, itemList):
        bboxList = itemObject["bbox"]

        centerX = (bboxList[0] + bboxList[2]) / 2

        left = None
        right = None

        for a in range(len(lineList)):
            bboxLineList = lineList[a]

            if self._overlap(bboxLineList[1], bboxLineList[3], bboxList[1], bboxList[3]) < (bboxList[3] - bboxList[1]) * self.levelLineCover:
                continue

            if bboxLineList[2] <= centerX and (left == None or bboxLineList[2] > left):
                left = bboxLineList[2]

            if bboxLineList[0] >= centerX and (right == None or bboxLineList[0] < right):
                right = bboxLineList[0]

        bandList = self._bandFind(bboxList, horizontalList)

        if left == None or right == None or bandList == None:
            return []

        resultList = []

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            centerOtherX = (bboxOtherList[0] + bboxOtherList[2]) / 2
            centerOtherY = (bboxOtherList[1] + bboxOtherList[3]) / 2

            if centerOtherX <= left or centerOtherX >= right or centerOtherY <= bandList[0] or centerOtherY >= bandList[1]:
                continue

            if self._stackLetterCheck(self._textClean(itemList[a]["text"])) == False:
                return []

            resultList.append(itemList[a])

        return self._stackDoubleSpan(resultList)

    def _stackDoubleCheck(self, itemObject):
        bboxList = itemObject["bbox"]

        width = bboxList[2] - bboxList[0]
        height = bboxList[3] - bboxList[1]

        return itemObject.get("isVertical") != True and len(self._textClean(itemObject["text"])) == 2 and width >= height and width <= height * self.levelStackWidth

    def _stackDoubleSpan(self, memberList):
        top = None
        bottom = None

        count = 0

        for a in range(len(memberList)):
            if self._stackDoubleCheck(memberList[a]):
                count += 1

                top = memberList[a]["bbox"][1] if top == None else min(top, memberList[a]["bbox"][1])
                bottom = memberList[a]["bbox"][3] if bottom == None else max(bottom, memberList[a]["bbox"][3])

        if count < self.countStackDouble:
            return []

        resultList = []

        for a in range(len(memberList)):
            if memberList[a]["bbox"][1] >= top and memberList[a]["bbox"][3] <= bottom:
                resultList.append(memberList[a])

        return resultList

    def _stackRowCount(self, memberList):
        memberSortedList = sorted(memberList, key=lambda itemObject: itemObject["bbox"][1])

        count = 1

        for a in range(1, len(memberSortedList)):
            if self._rangeCheck(memberSortedList[a - 1]["bbox"], memberSortedList[a]["bbox"]) == False:
                count += 1

        return count

    def _stackTitleBuild(self, memberList):
        bboxList = list(memberList[0]["bbox"])

        for a in range(len(memberList)):
            bboxList = self._bboxExpand(bboxList, memberList[a]["bbox"])

        leftList = []
        rightList = []

        for a in range(len(memberList)):
            bboxMemberList = memberList[a]["bbox"]

            text = self._textClean(memberList[a]["text"])

            if len(text) == 2 and memberList[a].get("isVertical"):
                leftList.append({"y": bboxMemberList[1], "text": text})
            elif len(text) == 2:
                leftList.append({"y": bboxMemberList[1], "text": text[0]})
                rightList.append({"y": bboxMemberList[1], "text": text[1]})
            elif bboxMemberList[0] - bboxList[0] <= bboxList[2] - bboxMemberList[2]:
                leftList.append({"y": bboxMemberList[1], "text": text})
            else:
                rightList.append({"y": bboxMemberList[1], "text": text})

        leftList.sort(key=lambda partObject: partObject["y"])
        rightList.sort(key=lambda partObject: partObject["y"])

        text = ""

        for a in range(len(leftList)):
            text += leftList[a]["text"]

        for a in range(len(rightList)):
            text += rightList[a]["text"]

        return {"text": text, "bbox": bboxList}

    def _stackSparseMember(self, itemObject, lineList, horizontalList, itemList):
        bboxList = itemObject["bbox"]

        centerX = (bboxList[0] + bboxList[2]) / 2

        left = None
        right = None

        for a in range(len(lineList)):
            bboxLineList = lineList[a]

            if self._overlap(bboxLineList[1], bboxLineList[3], bboxList[1], bboxList[3]) < (bboxList[3] - bboxList[1]) * self.levelLineCover:
                continue

            if bboxLineList[2] <= centerX and (left == None or bboxLineList[2] > left):
                left = bboxLineList[2]

            if bboxLineList[0] >= centerX and (right == None or bboxLineList[0] < right):
                right = bboxLineList[0]

        bandList = self._bandFind(bboxList, horizontalList)

        if left == None or right == None or bandList == None:
            return []

        resultList = []

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            centerOtherX = (bboxOtherList[0] + bboxOtherList[2]) / 2
            centerOtherY = (bboxOtherList[1] + bboxOtherList[3]) / 2

            if centerOtherX <= left or centerOtherX >= right or centerOtherY <= bandList[0] or centerOtherY >= bandList[1]:
                continue

            if len(self._textClean(itemList[a]["text"])) != 1 or self._letterContain(itemList[a]["text"]) == False:
                return []

            resultList.append(itemList[a])

        return sorted(resultList, key=lambda memberObject: memberObject["bbox"][1])

    def _rowMarkerCheck(self, itemObject, itemList, height, lineObject):
        bboxList = itemObject["bbox"]

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            gap = bboxOtherList[0] - bboxList[2]

            if itemList[a] is itemObject or gap < -height * self.levelMargin or gap > height * self.levelKeyGap or self._rangeCheck(bboxOtherList, bboxList) == False or len(self._textClean(itemList[a]["text"])) <= self.countStackLetter:
                continue

            if self._wallCount(lineObject["verticalList"], bboxList[2], bboxOtherList[0], bboxList) == 0:
                return True

        return False

    def _stackSparseCollect(self, itemList, lineObject, verticalList):
        height = self._heightMedian(itemList)

        usedList = []

        for a in range(len(itemList)):
            text = self._textClean(itemList[a]["text"])

            if itemList[a] in usedList or itemList[a].get("isVertical") or len(text) != 1 or self._letterContain(text) == False or self._rowMarkerCheck(itemList[a], itemList, height, lineObject):
                continue

            memberList = self._stackSparseMember(itemList[a], lineObject["verticalList"], lineObject["horizontalList"], itemList)

            if len(memberList) < self.countSparseMinimum:
                continue

            isSparse = True

            for b in range(1, len(memberList)):
                if memberList[b]["bbox"][1] - memberList[b - 1]["bbox"][3] < height * self.levelSparseGap:
                    isSparse = False

            if isSparse == False:
                continue

            verticalList.append(self._stackTitleBuild(memberList))

            usedList = usedList + memberList

        resultList = []

        for a in range(len(itemList)):
            if itemList[a] not in usedList:
                resultList.append(itemList[a])

        return resultList

    def _stackTitleCollect(self, itemList, lineObject, verticalList):
        usedList = []

        for a in range(len(itemList)):
            if itemList[a] in usedList or self._stackDoubleCheck(itemList[a]) == False or self._stackLetterCheck(self._textClean(itemList[a]["text"])) == False or self._rowMarkerCheck(itemList[a], itemList, self._heightMedian(itemList), lineObject):
                continue

            memberList = self._stackMemberCollect(itemList[a], lineObject["verticalList"], lineObject["horizontalList"], itemList)

            if len(memberList) == 0 or self._stackRowCount(memberList) < self.countVerticalMinimum:
                continue

            verticalList.append(self._stackTitleBuild(memberList))

            usedList = usedList + memberList

        resultList = []

        for a in range(len(itemList)):
            if itemList[a] not in usedList:
                resultList.append(itemList[a])

        return resultList

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

    def _arcRuleCheck(self, groupList, horizontalList):
        for a in range(len(groupList)):
            for b in range(len(groupList)):
                if groupList[a]["bbox"][1] < groupList[b]["bbox"][1] and self._ruleBetweenCheck(horizontalList, groupList[a]["bbox"], groupList[b]["bbox"]):
                    return True

        return False

    def _arcFit(self, itemList, height, horizontalList):
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

            if len(groupList) < self.countArcMinimum or self._arcRuleCheck(groupList, horizontalList):
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

                if bboxMarkList[0] >= bboxList[0] and bboxMarkList[2] <= bboxList[2] and bboxMarkList[1] >= bboxList[1] and bboxMarkList[3] <= bboxList[3]:
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

                if circleList[b].get("isBox", False):
                    continue

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

    def _titleStack(self, verticalList, height, lineObject):
        verticalSortedList = sorted(verticalList, key=lambda itemObject: itemObject["bbox"][1])

        resultList = []

        for a in range(len(verticalSortedList)):
            bboxList = verticalSortedList[a]["bbox"]

            isJoined = False

            for b in range(len(resultList)):
                bboxLastList = resultList[b]["bbox"]

                if abs((bboxList[0] + bboxList[2]) / 2 - (bboxLastList[0] + bboxLastList[2]) / 2) > height * self.levelMargin * 2 or abs((bboxList[2] - bboxList[0]) - (bboxLastList[2] - bboxLastList[0])) > height * self.levelMargin * 2 or bboxList[1] < bboxLastList[3] or bboxList[1] - bboxLastList[3] > height * self.levelTitleStack or self._ruleBetweenCheck(lineObject["horizontalList"], bboxLastList, bboxList) or self._wallCheck(lineObject["verticalList"], bboxList[2], math.inf, bboxList) == False:
                    continue

                resultList[b] = {"text": resultList[b]["text"] + verticalSortedList[a]["text"], "bbox": self._bboxExpand(bboxLastList, bboxList)}

                isJoined = True

                break

            if isJoined == False:
                resultList.append(dict(verticalSortedList[a]))

        return resultList

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

    def _digitGroupList(self, digitList):
        if len(digitList) < 2:
            return [digitList]

        pitch = -1

        for a in range(1, len(digitList)):
            distance = digitList[a]["start"] - digitList[a - 1]["start"]

            if distance > 0 and (pitch < 0 or distance < pitch):
                pitch = distance

        resultList = [[digitList[0]]]

        for a in range(1, len(digitList)):
            ratio = (digitList[a]["start"] - digitList[a - 1]["start"]) / pitch if pitch > 0 else 1

            if abs(ratio - round(ratio)) > self.levelPitch:
                resultList.append([])

            resultList[len(resultList) - 1].append(digitList[a])

        return resultList

    def _unitGroupText(self, groupList, labelList):
        partList = []

        for a in range(len(groupList)):
            partText = ""

            for b in range(len(groupList[a])):
                partText += groupList[a][b]["text"]

            partList.append({"text": partText, "center": (groupList[a][0]["start"] + groupList[a][len(groupList[a]) - 1]["end"]) / 2, "labelList": []})

        for a in range(len(labelList)):
            centerX = (labelList[a]["bbox"][0] + labelList[a]["bbox"][2]) / 2

            indexBest = 0

            for b in range(len(partList)):
                if abs(partList[b]["center"] - centerX) < abs(partList[indexBest]["center"] - centerX):
                    indexBest = b

            partList[indexBest]["labelList"].append(labelList[a]["text"].strip())

        textList = []

        for a in range(len(partList)):
            textList.append(partList[a]["text"])

            textList = textList + partList[a]["labelList"]

        return " ".join(textList)

    def _unitIsolatedCheck(self, itemList, labelObject):
        bboxList = labelObject["bbox"]

        reach = (bboxList[3] - bboxList[1]) * self.levelUnitIsolate

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            if itemList[a] is labelObject or itemList[a]["type"] != "key" or self._overlap(bboxList[0], bboxList[2], bboxOtherList[0], bboxOtherList[2]) <= 0:
                continue

            if bboxOtherList[3] > bboxList[1] - reach and bboxOtherList[1] < bboxList[3] + reach and self._overlap(bboxList[1], bboxList[3], bboxOtherList[1], bboxOtherList[3]) < (bboxList[3] - bboxList[1]) * self.levelParagraphOverlap:
                return False

        return True

    def _unitLabelRow(self, itemList, height):
        resultList = []

        for a in range(len(itemList)):
            if itemList[a]["type"] != "key" or (self._shortUnitCheck(itemList[a], height) == False and (itemList[a]["bbox"][3] - itemList[a]["bbox"][1] > height * self.levelUnitSize or self._unitIsolatedCheck(itemList, itemList[a]) == False)):
                continue

            isAdded = False

            for b in range(len(resultList)):
                if abs(resultList[b]["labelList"][0]["bbox"][1] - itemList[a]["bbox"][1]) <= height * self.levelMargin and abs(resultList[b]["labelList"][0]["bbox"][3] - itemList[a]["bbox"][3]) <= height * self.levelMargin:
                    resultList[b]["labelList"].append(itemList[a])

                    isAdded = True

                    break

            if isAdded == False:
                resultList.append({"labelList": [itemList[a]], "valueList": []})

        for a in range(len(resultList)):
            resultList[a]["labelList"].sort(key=lambda labelObject: labelObject["bbox"][2])

        return resultList

    def _unitColumnAssign(self, itemList, height, usedList):
        rowList = self._unitLabelRow(itemList, height)

        for a in range(len(itemList)):
            valueObject = itemList[a]

            if valueObject["type"] != "value":
                continue

            rowBest = None
            labelBest = None

            for b in range(len(rowList)):
                labelList = rowList[b]["labelList"]

                if len(labelList) < 2:
                    continue

                for c in range(len(labelList)):
                    bboxList = labelList[c]["bbox"]

                    if bboxList[3] > valueObject["bbox"][1] + height * self.levelMargin:
                        continue

                    if valueObject["bbox"][2] < bboxList[0] - height * self.levelUnitAlign or valueObject["bbox"][2] > bboxList[2] + height * self.levelUnitAlign:
                        continue

                    if labelBest == None or bboxList[3] > labelBest["bbox"][3]:
                        rowBest = rowList[b]
                        labelBest = labelList[c]

            if rowBest != None:
                rowBest["valueList"].append({"value": valueObject, "label": labelBest})

        for a in range(len(rowList)):
            if len(rowList[a]["valueList"]) < 2:
                continue

            for b in range(len(rowList[a]["valueList"])):
                rowList[a]["valueList"][b]["value"]["unit"] = rowList[a]["valueList"][b]["label"]["text"].strip()

            for b in range(len(rowList[a]["labelList"])):
                usedList.append(rowList[a]["labelList"][b])

    def _scaleLabelCheck(self, labelList):
        for a in range(len(labelList)):
            labelText = self._textClean(labelList[a]["text"])

            if len(labelText) == 0:
                return False

            for b in range(len(labelText)):
                value = unicodedata.numeric(labelText[b], 0)

                if value < 10:
                    return False

                while value >= 10 and value % 10 == 0:
                    value = value / 10

                if value != 1:
                    return False

        return True

    def _scaleUnitFind(self, labelList, valueObject, height):
        labelLast = labelList[0]

        for a in range(len(labelList)):
            if labelList[a]["bbox"][2] > labelLast["bbox"][2]:
                labelLast = labelList[a]

        if valueObject["bbox"][2] < labelLast["bbox"][0] - height * self.levelUnitAlign or valueObject["bbox"][2] > labelLast["bbox"][2] + height * self.levelUnitAlign:
            return None

        return labelLast

    def _unitAbove(self, itemList, height):
        usedList = []

        self._unitColumnAssign(itemList, height, usedList)

        for a in range(len(itemList)):
            valueObject = itemList[a]

            if valueObject["type"] != "value" or "unit" in valueObject:
                continue

            bboxValueList = valueObject["bbox"]

            labelList = []

            for b in range(len(itemList)):
                labelObject = itemList[b]

                bboxList = labelObject["bbox"]

                if labelObject["type"] != "key" or labelObject in usedList or (self._shortUnitCheck(labelObject, height) == False and (bboxList[3] - bboxList[1] > height * self.levelUnitSize or self._unitIsolatedCheck(itemList, labelObject) == False)):
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

            valueObject["isUnitOwn"] = True

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                if itemList[b]["type"] != "key" or self._shortUnitCheck(itemList[b], height) == False or bboxList[2] > bboxValueList[0] or abs(bboxList[1] - labelList[0]["bbox"][1]) > height * self.levelMargin or abs(bboxList[3] - labelList[0]["bbox"][3]) > height * self.levelMargin:
                    continue

                isBlocked = False

                for c in range(len(itemList)):
                    bboxOtherList = itemList[c]["bbox"]

                    if itemList[c] is not valueObject and self._shortUnitCheck(itemList[c], height) == False and bboxOtherList[0] >= bboxList[2] and bboxOtherList[2] <= bboxValueList[0] and self._overlap(bboxOtherList[1], bboxOtherList[3], bboxList[1], bboxValueList[3]) > 0:
                        isBlocked = True

                        break

                if isBlocked == False:
                    usedList.append(itemList[b])

            if self._scaleLabelCheck(labelList):
                labelLast = self._scaleUnitFind(labelList, valueObject, height)

                if labelLast != None:
                    valueObject["unit"] = labelLast["text"].strip()

                    for b in range(len(labelList)):
                        usedList.append(labelList[b])

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

            groupList = self._digitGroupList(digitList)

            if len(groupList) > 1:
                valueObject["text"] = self._unitGroupText(groupList, labelList)
                valueObject["isUnitOwn"] = True
                valueObject["isUnitGroup"] = True

                for b in range(len(labelList)):
                    usedList.append(labelList[b])

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

    def _unitRowAssign(self, pairList):
        groupList = []

        for a in range(len(pairList)):
            if "anchor" not in pairList[a]:
                continue

            rowObject = self._rowFind(pairList[a]["keyList"], pairList[a]["anchor"])

            if rowObject == None:
                continue

            isAdded = False

            for b in range(len(groupList)):
                if self._overlap(groupList[b]["bbox"][0], groupList[b]["bbox"][2], rowObject["bbox"][0], rowObject["bbox"][2]) > 0:
                    groupList[b]["pairList"].append(pairList[a])

                    isAdded = True

                    break

            if isAdded == False:
                groupList.append({"bbox": rowObject["bbox"], "pairList": [pairList[a]]})

        for a in range(len(groupList)):
            unitList = []

            for b in range(len(groupList[a]["pairList"])):
                unit = groupList[a]["pairList"][b]["unit"]

                if unit != "" and unit not in unitList:
                    unitList.append(unit)

            if len(unitList) != 1:
                continue

            for b in range(len(groupList[a]["pairList"])):
                groupList[a]["pairList"][b]["unit"] = unitList[0]

    def _outsideLineJoin(self, outsideLineList, height):
        outsideLineList.sort(key=lambda itemObject: itemObject["bbox"][0])

        a = 0

        while a < len(outsideLineList):
            isJoined = False

            for b in range(a + 1, len(outsideLineList)):
                gap = outsideLineList[b]["bbox"][0] - outsideLineList[a]["bbox"][2]

                if gap >= 0 and gap <= height * self.levelFieldGap and self._rangeCheck(outsideLineList[a]["bbox"], outsideLineList[b]["bbox"]):
                    outsideLineList[a]["text"] = f"{outsideLineList[a]['text']} {outsideLineList[b]['text']}"
                    outsideLineList[a]["bbox"] = self._bboxExpand(outsideLineList[a]["bbox"], outsideLineList[b]["bbox"])

                    del outsideLineList[b]

                    isJoined = True

                    break

            if isJoined == False:
                a += 1

    def _outsideLineBuild(self, restList, outsideLineList, height):
        resultList = []

        lineObject = {}

        for a in range(len(restList)):
            if restList[a]["isOutside"] == False:
                resultList.append(restList[a])

                continue

            index = restList[a]["detectionIndex"]

            if index not in lineObject:
                lineObject[index] = []

            lineObject[index].append(restList[a])

        for index in lineObject:
            partList = sorted(lineObject[index], key=lambda itemObject: itemObject["bbox"][0])

            text = ""
            bboxList = list(partList[0]["bbox"])

            for a in range(len(partList)):
                textPart = partList[a]["text"].strip()

                if len(text) > 0 and (unicodedata.category(text[-1]) != "Nd" or unicodedata.category(textPart[0:1] or " ") != "Nd"):
                    text += " "

                text += textPart

                bboxList = self._bboxExpand(bboxList, partList[a]["bbox"])

            outsideLineList.append({"text": text, "bbox": bboxList, "page": partList[0]["page"]})

        self._outsideLineJoin(outsideLineList, height)

        return resultList

    def _cellFind(self, bboxList, lineObject):
        centerX = (bboxList[0] + bboxList[2]) / 2

        left = None
        right = None

        for a in range(len(lineObject["verticalList"])):
            bboxLineList = lineObject["verticalList"][a]

            if self._overlap(bboxLineList[1], bboxLineList[3], bboxList[1], bboxList[3]) < (bboxList[3] - bboxList[1]) * self.levelLineCover:
                continue

            if bboxLineList[2] <= centerX and (left == None or bboxLineList[2] > left):
                left = bboxLineList[2]

            if bboxLineList[0] >= centerX and (right == None or bboxLineList[0] < right):
                right = bboxLineList[0]

        centerY = (bboxList[1] + bboxList[3]) / 2

        bandList = self._bandFind([bboxList[0], centerY, bboxList[2], centerY], lineObject["horizontalList"])

        if left == None or right == None or bandList == None:
            return None

        reach = (bboxList[3] - bboxList[1]) * self.levelCellDouble

        for a in range(len(lineObject["verticalList"])):
            bboxLineList = lineObject["verticalList"][a]

            if self._overlap(bboxLineList[1], bboxLineList[3], bboxList[1], bboxList[3]) < (bboxList[3] - bboxList[1]) * self.levelLineCover:
                continue

            if bboxLineList[2] <= left and left - bboxLineList[2] <= reach:
                left = bboxLineList[2]

            if bboxLineList[0] >= right and bboxLineList[0] - right <= reach:
                right = bboxLineList[0]

        return (left, right, bandList[0], bandList[1])

    def _cellRowSplitCheck(self, itemList, cell, height, bboxUpperList, bboxLowerList):
        isUpper = False
        isLower = False

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            if bboxList[0] < cell[1] or bboxList[0] - cell[1] > height * self.levelCellReach:
                continue

            isUpperItem = self._rangeCheck(bboxList, bboxUpperList)
            isLowerItem = self._rangeCheck(bboxList, bboxLowerList)

            if isUpperItem and isLowerItem == False:
                isUpper = True

            if isLowerItem:
                isLower = True

        return isUpper and (isLower == False or self._rangeCheck(bboxUpperList, bboxLowerList) == False)

    def _cellLineMerge(self, memberList, itemList, cell, height):
        memberSortedList = sorted(memberList, key=lambda itemObject: itemObject["bbox"][1])

        rowList = [[memberSortedList[0]]]

        for a in range(1, len(memberSortedList)):
            if self._cellRowSplitCheck(itemList, cell, height, memberSortedList[a - 1]["bbox"], memberSortedList[a]["bbox"]):
                return memberList

            if self._rangeCheck(rowList[len(rowList) - 1][0]["bbox"], memberSortedList[a]["bbox"]):
                rowList[len(rowList) - 1].append(memberSortedList[a])
            else:
                rowList.append([memberSortedList[a]])

        if len(rowList) != self.countCellRow:
            return memberList

        text = ""

        bboxList = list(memberSortedList[0]["bbox"])

        for a in range(len(rowList)):
            rowList[a].sort(key=lambda itemObject: itemObject["bbox"][0])

            for b in range(len(rowList[a])):
                text = self._textAppend(text, rowList[a][b]["text"])

                bboxList = self._bboxExpand(bboxList, rowList[a][b]["bbox"])

        resultObject = dict(memberSortedList[0])

        resultObject["text"] = text
        resultObject["bbox"] = bboxList

        return [resultObject]

    def _cellStackMerge(self, restList, lineObject, height, itemList):
        cellObject = {}

        resultList = []

        for a in range(len(restList)):
            cell = self._cellFind(restList[a]["bbox"], lineObject)

            if cell == None or cell[1] - cell[0] > height * self.levelCellLabel or restList[a].get("isOption") or restList[a].get("isMark") or restList[a].get("circleIndex", -1) >= 0 or self._letterContain(restList[a]["text"]) == False:
                resultList.append(restList[a])

                continue

            if cell not in cellObject:
                cellObject[cell] = []

            cellObject[cell].append(restList[a])

        for cell in cellObject:
            resultList = resultList + self._cellLineMerge(cellObject[cell], itemList, cell, height)

        return resultList

    def _cellLeftCheck(self, itemList, cell, height, bboxKeyList):
        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            if bboxList[2] <= cell[0] + height * self.levelMargin and cell[0] - bboxList[2] <= height * self.levelCellReach and self._rangeCheck(bboxList, bboxKeyList):
                return True

        return False

    def _cellKeyList(self, memberList):
        heightMaximum = 0

        for a in range(len(memberList)):
            heightMaximum = max(heightMaximum, memberList[a]["bbox"][3] - memberList[a]["bbox"][1])

        resultList = []

        for a in range(len(memberList)):
            if memberList[a]["bbox"][3] - memberList[a]["bbox"][1] >= heightMaximum * (1 - self.levelCellSize):
                resultList.append(memberList[a])

        return sorted(resultList, key=lambda itemObject: itemObject["bbox"][1])

    def _cellLabelCheck(self, keyList, itemList, cell, height):
        for a in range(len(keyList)):
            if self._letterContain(keyList[a]["text"]) == False or self._cellLeftCheck(itemList, cell, height, keyList[a]["bbox"]):
                return False

        text = ""

        for a in range(len(keyList)):
            text = self._textAppend(text, keyList[a]["text"])

        return self._shortTextUnitCheck(self._textClean(text)) == False

    def _cellEnclosedCheck(self, memberList):
        if len(memberList) != 1:
            return False

        text = self._textClean(memberList[0]["text"])

        return len(text) > 0 and unicodedata.category(text[0]) == "Ps" and unicodedata.category(text[-1]) == "Pe"

    def _cellPlainCheck(self, memberList):
        for a in range(len(memberList)):
            if memberList[a].get("isOption") or memberList[a].get("isMark") or memberList[a].get("circleIndex", -1) >= 0:
                return False

        return True

    def _cellBlockCheck(self, cell, lineObject):
        blockList = lineObject.get("blockList", [])

        for a in range(len(blockList)):
            bboxList = blockList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            if centerX > cell[0] and centerX < cell[1] and centerY > cell[2] and centerY < cell[3]:
                return True

        return False

    def _cellLineGroup(self, memberList):
        lineList = []

        for a in range(len(memberList)):
            if len(lineList) > 0 and self._rangeCheck(lineList[len(lineList) - 1][0]["bbox"], memberList[a]["bbox"]):
                lineList[len(lineList) - 1].append(memberList[a])
            else:
                lineList.append([memberList[a]])

        for a in range(len(lineList)):
            lineList[a].sort(key=lambda itemObject: itemObject["bbox"][0])

        return lineList

    def _cellRowMatch(self, keyList, memberList):
        lineList = self._cellLineGroup(memberList)

        resultList = []

        for a in range(len(lineList)):
            resultList.append({"keyList": [], "memberList": lineList[a]})

        for a in range(len(keyList)):
            centerY = (keyList[a]["bbox"][1] + keyList[a]["bbox"][3]) / 2

            indexBest = 0
            distanceBest = -1

            for b in range(len(lineList)):
                distance = abs((lineList[b][0]["bbox"][1] + lineList[b][0]["bbox"][3]) / 2 - centerY)

                if distanceBest < 0 or distance < distanceBest:
                    distanceBest = distance
                    indexBest = b

            resultList[indexBest]["keyList"].append(keyList[a])

        matchList = []

        for a in range(len(resultList)):
            keyOverlapList = []

            for b in range(len(resultList[a]["keyList"])):
                if self._overlap(resultList[a]["keyList"][b]["bbox"][1], resultList[a]["keyList"][b]["bbox"][3], resultList[a]["memberList"][0]["bbox"][1], resultList[a]["memberList"][0]["bbox"][3]) > 0:
                    keyOverlapList.append(resultList[a]["keyList"][b])

            if len(keyOverlapList) > 0:
                resultList[a]["keyList"] = keyOverlapList

            if len(resultList[a]["keyList"]) > 0:
                matchList.append(resultList[a])

        return matchList

    def _cellValueText(self, memberList):
        lineList = self._cellLineGroup(memberList)

        textList = []

        for a in range(len(lineList)):
            partList = []

            for b in range(len(lineList[a])):
                textPart = lineList[a][b]["text"].strip()

                if textPart.startswith(self.textMark) or textPart.startswith(self.textOption):
                    partList.append(textPart)

                    continue

                partList.append(f"{self.textMark} {textPart}" if lineList[a][b].get("isMark") else f"{self.textOption} {textPart}" if lineList[a][b].get("isOption") else textPart)

            textList.append(" ".join(partList))

        return " / ".join(textList)

    def _cellCenterCheck(self, memberList, cell, height):
        left = memberList[0]["bbox"][0]
        right = memberList[0]["bbox"][2]

        for a in range(len(memberList)):
            left = min(left, memberList[a]["bbox"][0])
            right = max(right, memberList[a]["bbox"][2])

        return abs((left + right) / 2 - (cell[0] + cell[1]) / 2) <= height * self.levelCellInside

    def _cellInsideCheck(self, keyList, cell, height):
        for a in range(len(keyList)):
            if keyList[a]["bbox"][0] < cell[0] - height * self.levelCellInside or keyList[a]["bbox"][2] > cell[1] + height * self.levelCellInside:
                return False

        return True

    def _cellSelfFieldCheck(self, cell, memberList, height):
        top = memberList[0]["bbox"][1]
        bottom = memberList[0]["bbox"][3]
        left = memberList[0]["bbox"][0]
        right = memberList[0]["bbox"][2]

        for a in range(len(memberList)):
            if memberList[a].get("isOption") or memberList[a].get("isMark"):
                return False

            top = min(top, memberList[a]["bbox"][1])
            bottom = max(bottom, memberList[a]["bbox"][3])
            left = min(left, memberList[a]["bbox"][0])
            right = max(right, memberList[a]["bbox"][2])

        spaceBelow = cell[3] - bottom

        if spaceBelow >= height * self.levelSelfField and top - cell[2] <= spaceBelow * self.levelSelfFieldRatio:
            return True

        spaceRight = cell[1] - right

        return left - cell[0] <= height * self.levelCellInside and spaceRight >= (right - left) * self.levelCellValue and spaceRight >= height * self.levelKeyReach

    def _cellPairAppend(self, keyList, memberList, height, verticalList, lineObject, pairList):
        key = ""

        bboxKeyList = list(keyList[0]["bbox"])

        for a in range(len(keyList)):
            key = self._textAppend(key, keyList[a]["text"])

            bboxKeyList = self._bboxExpand(bboxKeyList, keyList[a]["bbox"])

        sectionList = self._sectionCollect(bboxKeyList, bboxKeyList[0], verticalList, height, lineObject["verticalList"], lineObject["horizontalList"])

        groupList = []

        for a in range(1, len(sectionList)):
            groupList.append(sectionList[a]["text"])

        bboxFullList = list(bboxKeyList)

        for a in range(len(memberList)):
            bboxFullList = self._bboxExpand(bboxFullList, memberList[a]["bbox"])

        pairList.append({
            "y": bboxKeyList[1],
            "bbox": bboxKeyList,
            "bboxKey": bboxKeyList,
            "bboxFull": bboxFullList,
            "section": sectionList[0]["text"] if len(sectionList) > 0 else "",
            "group": " / ".join(groupList),
            "sectionList": sectionList,
            "row": "",
            "key": key,
            "formula": "",
            "value": self._cellValueText(memberList)
        })

    def _cellPairBuild(self, restList, lineObject, height, itemList, verticalList, pairList):
        cellObject = {}

        for a in range(len(restList)):
            cell = self._cellFind(restList[a]["bbox"], lineObject)

            if cell != None:
                if cell not in cellObject:
                    cellObject[cell] = []

                cellObject[cell].append(restList[a])

        usedList = []

        for cell in cellObject:
            keyList = self._cellKeyList(cellObject[cell])

            if cell[1] - cell[0] > height * self.levelCellLabel or self._cellInsideCheck(keyList, cell, height) == False or self._cellLabelCheck(keyList, itemList, cell, height) == False or self._cellSelfFieldCheck(cell, cellObject[cell], height):
                continue

            for cellOther in cellObject:
                if cellOther[2] != cell[2] or cellOther[3] != cell[3] or cellOther[0] < cell[1] or cellOther[0] - cell[1] > height * self.levelCellReach or cellOther[1] - cellOther[0] < (cell[1] - cell[0]) * self.levelCellValue or self._cellPlainCheck(cellObject[cellOther]) == False or self._cellSelfFieldCheck(cellOther, cellObject[cellOther], height):
                    continue

                memberList = sorted(cellObject[cellOther], key=lambda itemObject: (itemObject["bbox"][1], itemObject["bbox"][0]))

                if self._cellInsideCheck(memberList, cellOther, height) == False:
                    continue

                matchList = self._cellRowMatch(keyList, memberList)

                if len(cellObject[cell]) == 1:
                    matchList = [{"keyList": keyList, "memberList": memberList}]

                for a in range(len(matchList)):
                    if self._cellCenterCheck(matchList[a]["memberList"], cellOther, height) or self._cellEnclosedCheck(matchList[a]["memberList"]) or self._segmentLabelPairCheck([{"itemList": matchList[a]["keyList"]}, {"itemList": matchList[a]["memberList"]}], lineObject["verticalList"], height, itemList):
                        continue

                    self._cellPairAppend(matchList[a]["keyList"], matchList[a]["memberList"], height, verticalList, lineObject, pairList)

                    usedList = usedList + matchList[a]["keyList"] + matchList[a]["memberList"]

                break

        resultList = []

        for a in range(len(restList)):
            if restList[a] not in usedList:
                resultList.append(restList[a])

        return resultList

    def _cellProbe(self, bboxList, height, lineObject):
        centerY = (bboxList[1] + bboxList[3]) / 2

        bandList = self._bandFind([bboxList[0], centerY, bboxList[0] + height, centerY], lineObject["horizontalList"])

        top = centerY - height / 2
        bottom = centerY + height / 2

        if bandList != None:
            top = max(top, bandList[0])
            bottom = min(bottom, bandList[1])

        return self._cellFind([bboxList[0], top, bboxList[0] + height, bottom], lineObject)

    def _cellMemberMerge(self, memberList):
        lineList = self._cellLineGroup(sorted(memberList, key=lambda itemObject: itemObject["bbox"][1]))

        text = ""

        bboxList = list(memberList[0]["bbox"])

        for a in range(len(lineList)):
            for b in range(len(lineList[a])):
                if len(text) > 0 and (lineList[a][b].get("isMark") or lineList[a][b].get("isOption")):
                    text += " / "

                if lineList[a][b].get("isMark"):
                    text += f"{self.textMark} "
                elif lineList[a][b].get("isOption"):
                    text += f"{self.textOption} "

                text = self._textAppend(text, lineList[a][b]["text"])

                bboxList = self._bboxExpand(bboxList, lineList[a][b]["bbox"])

        resultObject = dict(memberList[0])

        resultObject["text"] = text
        resultObject["bbox"] = bboxList

        return resultObject

    def _cellBelowFreeCheck(self, cellBelowList, cellObject, itemList, cell):
        memberList = []

        for a in range(len(cellBelowList)):
            memberList = memberList + cellObject[cellBelowList[a]]

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            if centerX < cell[0] or centerX > cell[1] or centerY < cellBelowList[0][2] or centerY > cellBelowList[0][3]:
                continue

            isFound = False

            for b in range(len(memberList)):
                bboxMemberList = memberList[b]["bbox"]

                if centerX >= bboxMemberList[0] and centerX <= bboxMemberList[2] and centerY >= bboxMemberList[1] and centerY <= bboxMemberList[3]:
                    isFound = True

                    break

            if isFound == False:
                return False

        return True

    def _lineFreeList(self, restList, lineItemList):
        resultList = []

        for a in range(len(restList)):
            bboxList = restList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            for b in range(len(lineItemList)):
                bboxLineList = lineItemList[b]["bbox"]

                if centerX >= bboxLineList[0] and centerX <= bboxLineList[2] and centerY >= bboxLineList[1] and centerY <= bboxLineList[3]:
                    resultList.append(restList[a])

                    break

        return resultList

    def _restRemove(self, restList, restUsedList):
        resultList = []

        for a in range(len(restList)):
            if restList[a] not in restUsedList:
                resultList.append(restList[a])

        return resultList

    def _sectionUsedAppend(self, pairList, sectionUsedList):
        for a in range(len(pairList)):
            for b in range(len(pairList[a]["sectionList"])):
                if pairList[a]["sectionList"][b] not in sectionUsedList:
                    sectionUsedList.append(pairList[a]["sectionList"][b])

    def _pairBboxFind(self, pairObject):
        if "bbox" in pairObject:
            return pairObject["bbox"]

        return pairObject["anchor"]["bbox"]

    def _pairRowBandList(self, pairList, horizontalList):
        resultList = []

        for a in range(len(pairList)):
            if pairList[a]["row"] == "" or pairList[a]["key"] == "" or self._numberValue(self._textClean(pairList[a]["row"])) < 0 or "anchor" not in pairList[a]:
                continue

            rowObject = self._rowFind(pairList[a]["keyList"], pairList[a]["anchor"])

            if rowObject == None:
                continue

            bandList = self._bandFind(rowObject["bbox"], horizontalList)

            if bandList != None:
                resultList.append({"pair": pairList[a], "band": bandList, "right": rowObject["bbox"][2]})

        return resultList

    def _pairCaptionSplit(self, pairObject, text, height, outsideLineList, numberPage):
        if "anchor" not in pairObject:
            return text

        textList = []

        for a in range(len(pairObject["keyList"])):
            keyObject = pairObject["keyList"][a]

            if self._shortUnitCheck(keyObject, height) and keyObject["bbox"][3] <= pairObject["anchor"]["bbox"][1] + height * self.levelCaptionOverlap:
                outsideLineList.append({"text": keyObject["text"].strip(), "bbox": list(keyObject["bbox"]), "page": numberPage})
            elif keyObject["type"] != "row":
                textList.append(keyObject["text"].strip())

        textList.append(pairObject["value"])

        return " ".join(textList).strip()

    def _pairEnclosedCheck(self, pairObject):
        text = self._textClean(pairObject["key"])

        return len(text) == 1 and unicodedata.category(text) == "No"

    def _tableBoundaryCheck(self, bboxList, verticalList, left, height):
        centerY = (bboxList[1] + bboxList[3]) / 2

        positionList = []

        for a in range(len(verticalList)):
            center = (verticalList[a][0] + verticalList[a][2]) / 2

            if center > left and center < bboxList[0] and verticalList[a][1] <= centerY and verticalList[a][3] >= centerY and verticalList[a][3] - verticalList[a][1] >= height * self.levelWallCutLength:
                positionList.append(center)

        positionList.sort()

        for a in range(1, len(positionList)):
            if positionList[a] - positionList[a - 1] > height * self.levelMargin and positionList[a] - positionList[a - 1] <= height * self.levelTableDouble:
                return True

        return False

    def _pairRowAttach(self, pairList, horizontalList, outsideLineList, numberPage, height, verticalList):
        rowBandList = self._pairRowBandList(pairList, horizontalList)

        resultList = []

        for a in range(len(pairList)):
            pairObject = pairList[a]

            if pairObject["row"] != "":
                resultList.append(pairObject)

                continue

            bboxList = self._pairBboxFind(pairObject)

            if self._pairEnclosedCheck(pairObject):
                outsideLineList.append({"text": f"{pairObject['key']} {pairObject['value']}", "bbox": list(bboxList), "page": numberPage})

                continue

            if len(self._textClean(pairObject["key"])) > self.countAttachKey:
                resultList.append(pairObject)

                continue

            bandList = self._bandFind([bboxList[0], (bboxList[1] + bboxList[3]) / 2, bboxList[2], (bboxList[1] + bboxList[3]) / 2], horizontalList)

            bandBest = None

            for b in range(len(rowBandList)):
                if bandList != None and bandList[0] >= rowBandList[b]["band"][0] - height * self.levelBandSame and bandList[1] <= rowBandList[b]["band"][1] + height * self.levelBandSame and bboxList[0] >= rowBandList[b]["right"] and self._tableBoundaryCheck(bboxList, verticalList, rowBandList[b]["right"], height) == False and (bandBest == None or rowBandList[b]["right"] > bandBest["right"]):
                    bandBest = rowBandList[b]

            if bandBest == None:
                resultList.append(pairObject)

                continue

            if "attachList" not in bandBest:
                bandBest["attachList"] = []

            text = f"{pairObject['key']} {pairObject['value']}".strip()

            bandBest["attachList"].append({"text": self._pairCaptionSplit(pairObject, text, height, outsideLineList, numberPage), "left": bboxList[0]})

        for a in range(len(rowBandList)):
            attachList = sorted(rowBandList[a].get("attachList", []), key=lambda attachObject: attachObject["left"])

            textList = []

            if rowBandList[a]["pair"]["value"] != "":
                textList.append(rowBandList[a]["pair"]["value"])

            for b in range(len(attachList)):
                textList.append(attachList[b]["text"])

            rowBandList[a]["pair"]["value"] = " / ".join(textList)

        return resultList

    def _cellHeaderRowCount(self, cellObject, cell, margin):
        count = 0

        for cellOther in cellObject:
            if abs(cellOther[2] - cell[2]) <= margin and abs(cellOther[3] - cell[3]) <= margin:
                count += 1

        return count

    def _cellHeaderBuild(self, restList, verticalList, sectionUsedList, height, lineObject, isSingle, itemList, pairList):
        memberAllList = list(restList)

        for a in range(len(verticalList)):
            if verticalList[a] not in sectionUsedList:
                memberAllList.append({"text": verticalList[a]["text"], "bbox": verticalList[a]["bbox"], "isTitle": True, "titleObject": verticalList[a]})

        cellObject = {}

        for a in range(len(memberAllList)):
            cell = self._cellProbe(memberAllList[a]["bbox"], height, lineObject)

            if cell != None:
                if cell not in cellObject:
                    cellObject[cell] = []

                cellObject[cell].append(memberAllList[a])

        margin = height * self.levelCellInside

        usedList = []

        for cell in cellObject:
            keyLineList = self._cellLineGroup(sorted(cellObject[cell], key=lambda itemObject: itemObject["bbox"][1]))

            if cell[3] - cell[2] > height * self.levelCellHeaderBand or len(keyLineList) != 1 or self._cellPlainCheck(keyLineList[0]) == False or self._cellTitleCheck(keyLineList[0]) or self._letterContain(self._cellMemberMerge(keyLineList[0])["text"]) == False:
                continue

            cellBelowList = []

            for cellOther in cellObject:
                if abs(cellOther[2] - cell[3]) <= margin and cellOther[0] >= cell[0] - margin and cellOther[1] <= cell[1] + margin:
                    cellBelowList.append(cellOther)

            if len(cellBelowList) == 0 or (len(cellBelowList) == 1) != isSingle:
                continue

            cellBelowList.sort(key=lambda cellBelow: self._cellMemberMerge(cellObject[cellBelow])["bbox"][0])

            right = 0

            for a in range(len(cellBelowList)):
                right = max(right, cellBelowList[a][1], self._cellMemberMerge(cellObject[cellBelowList[a]])["bbox"][2])

            if abs(cellBelowList[0][0] - cell[0]) > margin or abs(right - cell[1]) > margin or self._cellBelowFreeCheck(cellBelowList, cellObject, itemList, cell) == False:
                continue

            if len(cellBelowList) == 1 and (self._cellHeaderRowCount(cellObject, cell, margin) < self.countCellHeaderRow or self._cellHeaderRowCount(cellObject, cellBelowList[0], margin) != 1 or len(self._cellLineGroup(sorted(cellObject[cellBelowList[0]], key=lambda itemObject: itemObject["bbox"][1]))) != 1):
                continue

            textList = []

            isPlain = True

            for a in range(len(cellBelowList)):
                if self._cellPlainCheck(cellObject[cellBelowList[a]]) == False:
                    isPlain = False

                textList.append(self._cellMemberMerge(cellObject[cellBelowList[a]])["text"])

            if isPlain == False:
                continue

            memberObject = self._cellMemberMerge(cellObject[cellBelowList[0]])

            memberObject["text"] = " / ".join(textList)

            self._cellPairAppend([self._cellMemberMerge(keyLineList[0])], [memberObject], height, verticalList, lineObject, pairList)

            usedList = usedList + keyLineList[0]

            for a in range(len(cellBelowList)):
                for b in range(len(cellObject[cellBelowList[a]])):
                    memberObject = cellObject[cellBelowList[a]][b]

                    if memberObject.get("isTitle"):
                        sectionUsedList.append(memberObject["titleObject"])
                    else:
                        usedList.append(memberObject)

        return usedList

    def _wallThroughCheck(self, height, lineList, position, cell):
        margin = height * self.levelMargin

        for a in range(len(lineList)):
            if abs((lineList[a][0] + lineList[a][2]) / 2 - position) <= margin and lineList[a][1] <= cell[2] - height and lineList[a][3] >= cell[3] + height:
                return True

        return False

    def _cellVerticalCheck(self, memberList):
        lineList = self._cellLineGroup(sorted(memberList, key=lambda itemObject: itemObject["bbox"][1]))

        if len(lineList) <= self.countCellRow:
            return False

        for a in range(len(lineList)):
            text = ""

            for b in range(len(lineList[a])):
                text = self._textAppend(text, lineList[a][b]["text"])

            if len(text) > self.countUnitMaximum:
                return False

        return True

    def _valueKeyFirstCheck(self, valueList, cellObject):
        if len(valueList) < 2:
            return False

        if len(self._textClean(self._cellMemberMerge(cellObject[valueList[0]])["text"])) <= self.countUnitMaximum:
            return False

        for a in range(1, len(valueList)):
            if len(self._textClean(self._cellMemberMerge(cellObject[valueList[a]])["text"])) > self.countUnitMaximum:
                return False

        return True

    def _enclosedPairBuild(self, restList, height, verticalList, lineObject, pairList):
        usedList = []

        for a in range(len(restList)):
            text = self._textClean(restList[a]["text"])

            if len(text) < 2 or unicodedata.category(text[0]) != "Ps" or unicodedata.category(text[-1]) != "Pe":
                continue

            index = 1

            while index < len(text) - 1 and unicodedata.category(text[index])[0] == "L":
                index += 1

            if index == 1 or index == len(text) - 1 or unicodedata.category(text[index]) != "Nd":
                continue

            keyObject = dict(restList[a])
            keyObject["text"] = text[1:index]

            valueObject = dict(restList[a])
            valueObject["text"] = text[index:len(text) - 1]

            self._cellPairAppend([keyObject], [valueObject], height, verticalList, lineObject, pairList)

            usedList.append(restList[a])

        return usedList

    def _segmentLabelPairCheck(self, segment, lineList, height, itemList):
        if len(segment) != 2 or len(lineList) == 0:
            return False

        valueList = segment[1]["itemList"]

        text = ""

        left = valueList[0]["bbox"][0]
        right = valueList[0]["bbox"][2]

        for a in range(len(valueList)):
            text = self._textAppend(text, valueList[a]["text"])

            left = min(left, valueList[a]["bbox"][0])
            right = max(right, valueList[a]["bbox"][2])

        if len(text) < 2 or self._letterOnlyCheck(text) == False or (right - left) / len(text) < height * self.levelLabelPitch:
            return False

        centerY = (valueList[0]["bbox"][1] + valueList[0]["bbox"][3]) / 2

        positionList = []

        for a in range(len(lineList)):
            center = (lineList[a][0] + lineList[a][2]) / 2

            if lineList[a][1] <= centerY and lineList[a][3] >= centerY and center >= right - height * self.levelMargin:
                positionList.append(center)

        positionList.sort()

        if len(positionList) == 0:
            return False

        wallAfter = None

        for a in range(1, len(positionList)):
            if positionList[a] - positionList[0] > height:
                wallAfter = positionList[a]

                break

        if wallAfter == None or wallAfter - positionList[0] < height * self.levelLabelEmpty:
            return False

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2

            if centerX > positionList[0] and centerX < wallAfter and abs((bboxList[1] + bboxList[3]) / 2 - centerY) <= height:
                return False

        return True

    def _cellFilledCheck(self, itemList, cell):
        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            if centerX > cell[0] and centerX < cell[1] and centerY > cell[2] and centerY < cell[3]:
                return True

        return False

    def _cellLeftFilledCheck(self, cell, height, lineObject, itemList):
        centerY = (cell[2] + cell[3]) / 2

        probeX = cell[0] - height * self.levelCellLeftProbe - height / 2

        cellLeft = self._cellProbe([probeX, centerY - height / 2, probeX, centerY + height / 2], height, lineObject)

        if cellLeft == None or abs(cellLeft[2] - cell[2]) > height * self.levelBandSame or abs(cellLeft[3] - cell[3]) > height * self.levelBandSame:
            return False

        return self._cellFilledCheck(itemList, cellLeft)

    def _styleKeyCheck(self, keyList, valueList, memberList):
        styleKey = keyList[0].get("style", "")

        return styleKey != "" and memberList[0].get("style", "") == styleKey and valueList[0].get("style", "") != styleKey

    def _keyColumnCheck(self, cell, cellKey, pairList):
        for a in range(len(pairList)):
            if "anchor" in pairList[a]:
                bboxList = None

                for b in range(len(pairList[a]["keyList"])):
                    if pairList[a]["keyList"][b]["type"] == "key":
                        bboxList = pairList[a]["keyList"][b]["bbox"] if bboxList == None else self._bboxExpand(bboxList, pairList[a]["keyList"][b]["bbox"])
            else:
                bboxList = pairList[a].get("bboxKey")

            if bboxList == None:
                continue

            centerY = (bboxList[1] + bboxList[3]) / 2

            if bboxList[0] >= cell[0] and bboxList[2] <= cell[1] and (centerY < cellKey[2] or centerY > cellKey[3]):
                return True

        return False

    def _suffixUnitCheck(self, textSuffix):
        if len(textSuffix) == 0:
            return False

        index = 0

        while index < len(textSuffix) and self._scaleLabelCheck([{"text": textSuffix[index]}]):
            index += 1

        textUnit = textSuffix[index:]

        if textUnit == "" or self.reference.unitCheck(textUnit) or self.reference.captionCheck(textUnit, self.reference.dateCaptionList + self.reference.currencyList):
            return True

        if len(textSuffix) > self.countUnitMaximum:
            return False

        for a in range(len(textSuffix)):
            if self._wideCheck(textSuffix[a]) == False:
                return True

        return len(textSuffix) < 2

    def _shortTextUnitCheck(self, textItem):
        if len(textItem) > self.countUnitMaximum:
            return False

        return len(textItem) < 2 or self.reference.unitCheck(textItem) or self._scaleLabelCheck([{"text": textItem}]) or self.reference.captionCheck(textItem, self.reference.dateCaptionList + self.reference.currencyList)

    def _shortUnitCheck(self, itemObject, height):
        textItem = self._textClean(itemObject["text"])

        if len(textItem) > self.countUnitMaximum:
            return False

        bboxList = itemObject["bbox"]

        return bboxList[3] - bboxList[1] <= height * self.levelUnitSize or self._shortTextUnitCheck(textItem)

    def _cellBoxBelowCheck(self, cell, height, lineObject, itemList):
        margin = height * self.levelCellInside

        isBox = False

        for a in range(len(lineObject["horizontalList"])):
            bboxLineList = lineObject["horizontalList"][a]

            if abs((bboxLineList[1] + bboxLineList[3]) / 2 - cell[3]) > height * self.levelMargin or bboxLineList[0] < cell[0] - margin or bboxLineList[2] > cell[1] + margin:
                continue

            if bboxLineList[0] <= cell[0] + margin and bboxLineList[2] >= cell[1] - margin:
                continue

            for b in range(len(lineObject["horizontalList"])):
                bboxOtherList = lineObject["horizontalList"][b]

                gap = bboxOtherList[1] - bboxLineList[3]

                if abs(bboxOtherList[0] - bboxLineList[0]) <= height * self.levelMargin and abs(bboxOtherList[2] - bboxLineList[2]) <= height * self.levelMargin and gap >= height * self.levelCellInside and gap <= height * self.levelModuleBoxSize:
                    isBox = True

                    break

        if isBox == False:
            return False

        return self._cellFilledCheck(itemList, (cell[0], cell[1], cell[3], cell[3] + height * self.levelCellBelow)) == False

    def _cellBlankCheck(self, memberList, height):
        rowList = self._cellLineGroup(sorted(memberList, key=lambda itemObject: itemObject["bbox"][1]))

        for a in range(len(rowList)):
            lineList = sorted(rowList[a], key=lambda itemObject: itemObject["bbox"][0])

            for b in range(1, len(lineList)):
                if lineList[b]["bbox"][0] - lineList[b - 1]["bbox"][2] >= height * self.levelKeyReach:
                    return True

        return False

    def _cellAdjacentBuild(self, restList, height, lineObject, itemList, verticalList, pairList, pairKnownList):
        cellObject = {}

        for a in range(len(restList)):
            cell = self._cellProbe(restList[a]["bbox"], height, lineObject)

            if cell != None:
                if cell not in cellObject:
                    cellObject[cell] = []

                cellObject[cell].append(restList[a])

        margin = height * self.levelCellInside

        usedList = []

        for cell in sorted(cellObject, key=lambda cellSort: cellSort[0]):
            memberList = cellObject[cell]

            if memberList[0] in usedList or self._cellPlainCheck(memberList) == False:
                continue

            keyObject = self._cellMemberMerge(memberList)

            if self._shortUnitCheck(keyObject, height) or self._cellBlankCheck(memberList, height) or self._cellBoxBelowCheck(cell, height, lineObject, itemList) or self._cellSelfFieldCheck(cell, memberList, height) or self._letterContain(keyObject["text"]) == False or len(self._cellLineGroup(sorted(memberList, key=lambda itemObject: itemObject["bbox"][1]))) > self.countCellRow or self._cellBelowFreeCheck([cell], cellObject, itemList, cell) == False or self._cellLeftFilledCheck(cell, height, lineObject, restList):
                continue

            centerY = (cell[2] + cell[3]) / 2

            valueList = []

            right = cell[1]

            isFound = True

            while isFound:
                isFound = False

                for cellOther in cellObject:
                    if abs(cellOther[0] - right) <= margin and cellOther[2] <= centerY and cellOther[3] >= centerY and cellOther[1] > cellOther[0] and cellObject[cellOther][0] not in usedList and self._cellSelfFieldCheck(cellOther, cellObject[cellOther], height) == False and self._cellBelowFreeCheck([cellOther], cellObject, itemList, cellOther) and self._cellVerticalCheck(cellObject[cellOther]) == False and (len(valueList) == 0 or self._wallThroughCheck(height, lineObject["verticalList"], right, cell) == False) and (len(valueList) == 0 or self._cellRightEmptyCheck(cellOther, height, lineObject, itemList + verticalList) == False) and (len(valueList) == 0 or self._keyColumnCheck(cellOther, cell, pairKnownList + pairList) == False) and (len(valueList) == 0 or self._styleKeyCheck(memberList, cellObject[valueList[0]], cellObject[cellOther]) == False):
                        valueList.append(cellOther)

                        right = cellOther[1]

                        isFound = True

                        break

            if len(valueList) == 0 or self._valueKeyFirstCheck(valueList, cellObject):
                continue

            segment = [{"itemList": memberList}]

            for a in range(len(valueList)):
                segment.append({"itemList": cellObject[valueList[a]]})

            if self._segmentLabelRowCheck(segment, height, lineObject["horizontalList"], lineObject["verticalList"]) or self._segmentLabelPairCheck(segment, lineObject["verticalList"], height, itemList):
                continue

            textList = []

            for a in range(len(valueList)):
                textList.append(self._cellMemberMerge(cellObject[valueList[a]])["text"])

            valueObject = self._cellMemberMerge(cellObject[valueList[0]])

            valueObject["text"] = " / ".join(textList)

            self._cellPairAppend([keyObject], [valueObject], height, verticalList, lineObject, pairList)

            usedList = usedList + memberList

            for a in range(len(valueList)):
                usedList = usedList + cellObject[valueList[a]]

        return usedList

    def _cellRightEmptyCheck(self, cell, height, lineObject, itemList):
        margin = height * self.levelCellInside

        centerY = (cell[2] + cell[3]) / 2

        cellRight = self._cellProbe([cell[1] + margin, centerY - height / 2, cell[1] + margin, centerY + height / 2], height, lineObject)

        if cellRight == None or cellRight[2] > centerY or cellRight[3] < centerY or self._cellFilledCheck(itemList, cellRight):
            return False

        if abs(cellRight[0] - cell[1]) <= margin:
            return True

        return cellRight[0] > cell[1] and cellRight[0] - cell[1] <= height * self.levelCellReach and self._cellFilledCheck(itemList, (cell[1], cellRight[0], cellRight[2], cellRight[3])) == False

    def _cellRightPairEmptyFind(self, height, cell, lineObject, pairList):
        margin = height * self.levelCellInside

        centerY = (cell[2] + cell[3]) / 2

        cellRight = self._cellProbe([cell[1] + margin, centerY - height / 2, cell[1] + margin, centerY + height / 2], height, lineObject)

        if cellRight == None or abs(cellRight[0] - cell[1]) > margin or abs(cellRight[2] - cell[2]) > margin or abs(cellRight[3] - cell[3]) > margin:
            return None

        for a in range(len(pairList)):
            if "bboxKey" not in pairList[a] or pairList[a]["value"] != "":
                continue

            bboxList = pairList[a]["bboxKey"]

            centerKeyX = (bboxList[0] + bboxList[2]) / 2
            centerKeyY = (bboxList[1] + bboxList[3]) / 2

            if centerKeyX > cellRight[0] and centerKeyX < cellRight[1] and centerKeyY > cellRight[2] and centerKeyY < cellRight[3]:
                return pairList[a]

        return None

    def _cellUnitCollect(self, cell, restList, height, itemList, usedList):
        resultList = []

        for a in range(len(restList)):
            bboxList = restList[a]["bbox"]

            centerY = (bboxList[1] + bboxList[3]) / 2

            if restList[a] in usedList or bboxList[0] < cell[1] or centerY < cell[2] or centerY > cell[3] or self._shortUnitCheck(restList[a], height) == False:
                continue

            resultList.append(restList[a])

        limit = None

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            centerY = (bboxList[1] + bboxList[3]) / 2

            if bboxList[0] < cell[1] or centerY < cell[2] or centerY > cell[3] or self._shortUnitCheck(itemList[a], height):
                continue

            if limit == None or bboxList[0] < limit:
                limit = bboxList[0]

        unitList = []

        for a in range(len(resultList)):
            if limit == None or resultList[a]["bbox"][0] < limit:
                unitList.append(resultList[a])

        if len(unitList) < 2:
            return []

        unitList.sort(key=lambda itemObject: itemObject["bbox"][0])

        return unitList

    def _cellEmptyBuild(self, restList, height, lineObject, itemList, verticalList, pairList):
        cellObject = {}

        margin = height * self.levelCellInside

        for a in range(len(restList)):
            cell = self._cellProbe(restList[a]["bbox"], height, lineObject)

            if cell == None:
                continue

            for cellOther in cellObject:
                if abs(cellOther[0] - cell[0]) <= margin and abs(cellOther[1] - cell[1]) <= margin and abs(cellOther[2] - cell[2]) <= margin and abs(cellOther[3] - cell[3]) <= margin:
                    cell = cellOther

                    break

            if cell not in cellObject:
                cellObject[cell] = []

            cellObject[cell].append(restList[a])

        usedList = []

        for cell in sorted(cellObject, key=lambda cellSort: (cellSort[2], cellSort[0])):
            memberList = cellObject[cell]

            if self._cellPlainCheck(memberList) == False or self._cellBlockCheck(cell, lineObject):
                continue

            keyObject = self._cellMemberMerge(memberList)

            if self.textOption in keyObject["text"] or self.textMark in keyObject["text"]:
                continue

            isUnit = len(memberList) > 1

            for a in range(len(memberList)):
                if self._shortUnitCheck(memberList[a], height) == False:
                    isUnit = False

            if isUnit or len(self._textClean(keyObject["text"])) < 2 or self._letterContain(keyObject["text"]) == False:
                continue

            centerX = (cell[0] + cell[1]) / 2
            centerY = (cell[2] + cell[3]) / 2

            cellBelow = self._cellProbe([centerX - height / 2, cell[3] + margin, centerX - height / 2, cell[3] + margin + height], height, lineObject)

            isEmpty = self._cellRightEmptyCheck(cell, height, lineObject, itemList + verticalList + lineObject.get("blockList", []))

            if isEmpty == False:
                isEmpty = cellBelow != None and cellBelow[2] - cell[3] <= height * self.levelCellBelow and self._cellFilledCheck(itemList + verticalList + lineObject.get("blockList", []), cellBelow) == False

            if isEmpty == False:
                isEmpty = self._cellBoxBelowCheck(cell, height, lineObject, itemList + verticalList + lineObject.get("blockList", [])) or (self._cellSelfFieldCheck(cell, memberList, height) and self._cellBelowFreeCheck([cell], cellObject, itemList, cell))

            pairRightObject = None

            if isEmpty == False and len(self._cellLineGroup(sorted(memberList, key=lambda itemObject: itemObject["bbox"][1]))) <= self.countCellRow:
                pairRightObject = self._cellRightPairEmptyFind(height, cell, lineObject, pairList)

            if isEmpty == False and pairRightObject == None:
                continue

            unitList = self._cellUnitCollect(cell, restList, height, itemList, usedList)

            self._cellPairAppend([keyObject], unitList, height, verticalList, lineObject, pairList)

            pairList[len(pairList) - 1]["isSelfField"] = self._cellSelfFieldCheck(cell, memberList, height)

            if pairRightObject != None:
                pairObject = pairList.pop()

                pairObject["section"] = pairRightObject["section"]
                pairObject["sectionList"] = pairRightObject["sectionList"]

                if "column" in pairRightObject:
                    pairObject["column"] = pairRightObject["column"]

                if "block" in pairRightObject:
                    pairObject["block"] = pairRightObject["block"]

                pairList.insert(pairList.index(pairRightObject), pairObject)

            usedList = usedList + memberList + unitList

        return usedList

    def _cellTitleCheck(self, memberList):
        for a in range(len(memberList)):
            if memberList[a].get("isTitle"):
                return True

        return False

    def _segmentCaptionCheck(self, segment, itemList, height, horizontalList):
        bottom = 0

        for a in range(len(segment)):
            text = self._textClean("".join(self._columnText(segment[a])))

            if len(text) > self.countCaptionMaximum or self._letterOnlyCheck(text) == False:
                return False

            for b in range(len(segment[a]["itemList"])):
                bottom = max(bottom, segment[a]["itemList"][b]["bbox"][3])

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            gap = bboxList[1] - bottom

            if itemList[a]["type"] == "value" and gap >= -height * self.levelCaptionOverlap and gap <= height and self._overlap(bboxList[0], bboxList[2], segment[0]["x1"], segment[len(segment) - 1]["x2"]) > 0 and self._ruleBetweenCheck(horizontalList, [segment[0]["x1"], bottom - height, segment[len(segment) - 1]["x2"], bottom], bboxList) == False:
                return True

        return False

    def _letterOnlyCheck(self, text):
        for a in range(len(text)):
            if unicodedata.category(text[a])[0] != "L":
                return False

        return len(text) > 0

    def _segmentFreeCheck(self, segment):
        indexList = []

        for a in range(len(segment)):
            for b in range(len(segment[a]["itemList"])):
                if segment[a]["itemList"][b].get("isOutside"):
                    return True

                indexList.append(segment[a]["itemList"][b].get("detectionIndex", -1 - len(indexList)))

        return len(set(indexList)) == 1

    def _segmentLabelRowCheck(self, segment, height, horizontalList, lineList):
        bboxKeyList = segment[0]["itemList"][0]["bbox"]

        centerY = (bboxKeyList[1] + bboxKeyList[3]) / 2

        bandList = self._bandFind([bboxKeyList[0], centerY, bboxKeyList[0] + height, centerY], horizontalList)

        if bandList == None:
            return False

        right = 0

        for a in range(1, len(segment)):
            for b in range(len(segment[a]["itemList"])):
                right = max(right, segment[a]["itemList"][b]["bbox"][2])

        margin = height * self.levelMargin

        positionList = []

        for a in range(len(lineList)):
            center = (lineList[a][0] + lineList[a][2]) / 2

            if center <= bboxKeyList[0] or center >= right or lineList[a][1] > bandList[0] + margin or lineList[a][3] < bandList[1] - margin:
                continue

            if lineList[a][3] < bandList[1] + height:
                return False

            isNear = False

            for b in range(len(positionList)):
                if abs(positionList[b] - center) <= margin:
                    isNear = True

            if isNear == False:
                positionList.append(center)

        return len(positionList) >= self.countLabelRowCell

    def _segmentWallCheck(self, segment, lineList, height):
        if len(lineList) == 0:
            return True

        valueList = segment[1]["itemList"]

        for a in range(len(valueList)):
            bboxList = valueList[a]["bbox"]

            if self._wallCheck(lineList, bboxList[0] + height * self.levelMargin, bboxList[2] - height * self.levelMargin, bboxList):
                return False

        bboxValueList = list(valueList[0]["bbox"])

        for a in range(1, len(valueList)):
            bboxValueList = self._bboxExpand(bboxValueList, valueList[a]["bbox"])

        return self._wallCheck(lineList, segment[0]["x2"] - height * self.levelMargin, segment[1]["x1"] + height * self.levelMargin, bboxValueList)

    def _textPairBuild(self, restList, verticalList, height, lineList, horizontalList, itemList):
        pairList = []
        lineItemList = []

        pairItemList = []

        restList = self._verticalPair(restList, pairItemList, height) + pairItemList

        restList = self._letterLine(restList, height)

        restList = self._paragraphMerge(restList, height, horizontalList)

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
                        if self._shortTextUnitCheck(self._textClean(segment[c]["itemList"][d]["text"])) == False:
                            isShort = False

                keyText = self._textClean("".join(self._columnText(segment[0])))

                isSymbol = False

                for c in range(len(segment)):
                    if self._symbolCheck(self._textClean("".join(self._columnText(segment[c])))):
                        isSymbol = True

                cellKey = self._cellProbe(segment[0]["itemList"][0]["bbox"], height, {"verticalList": lineList, "horizontalList": horizontalList})

                restPlainList = []

                for c in range(len(restList)):
                    if restList[c].get("isOption") != True and restList[c].get("isMark") != True:
                        restPlainList.append(restList[c])

                isLeft = cellKey != None and (self._cellLeftFilledCheck(cellKey, height, {"verticalList": lineList, "horizontalList": horizontalList}, restPlainList) or self._cellSelfFieldCheck(cellKey, segment[0]["itemList"], height))

                if len(segment) < 2 or isShort or isSymbol or isLeft or self._letterContain(keyText) == False or self._segmentFreeCheck(segment) or self._segmentCaptionCheck(segment, itemList, height, horizontalList) or self._shortTextUnitCheck(keyText) or self._columnOption(segment[0]) or self._segmentLabelRowCheck(segment, height, horizontalList, lineList) or self._segmentLabelPairCheck(segment, lineList, height, itemList) or self._segmentWallCheck(segment, lineList, height) == False:
                    lineTextList = []

                    bboxLineList = None

                    countOption = 0

                    for c in range(len(segment)):
                        for d in range(len(segment[c]["itemList"])):
                            if segment[c]["itemList"][d].get("isOption") or segment[c]["itemList"][d].get("isMark"):
                                countOption += 1

                    for c in range(len(segment)):
                        columnItemList = sorted(segment[c]["itemList"], key=lambda itemObject: itemObject["bbox"][1])

                        if c > 0 and bboxLineList != None and self._wallCheck(lineList, segment[c - 1]["x2"] - height * self.levelMargin, segment[c]["x1"] + height * self.levelMargin, [0, max(bboxLineList[1], columnItemList[0]["bbox"][1]), 0, min(bboxLineList[3], columnItemList[len(columnItemList) - 1]["bbox"][3])]):
                            lineItemList.append({"text": " ".join(lineTextList), "bbox": bboxLineList, "band": a})

                            lineTextList = []

                            bboxLineList = None

                        for d in range(len(columnItemList)):
                            text = self._spaceNormalize(columnItemList[d]["text"])

                            lineTextList.append(f"{self.textMark} {text}" if columnItemList[d].get("isMark") else f"{self.textOption} {text}" if columnItemList[d].get("isOption") and (countOption > 1 or columnItemList[d].get("circleIndex", -1) < 0) else text)

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

                    textPart = "".join(partList) if self._wideCheck((partList[0] or " ")[-1:] or " ") else " ".join(partList)

                    textList.append(f"{self.textMark} {textPart}" if isMark else f"{self.textOption} {textPart}" if c > 0 and self._columnOption(segment[c]) else textPart)

                sectionList = self._sectionCollect(bboxSegmentList, bboxSegmentList[0], verticalList, height, lineList, horizontalList)

                groupList = []

                for c in range(1, len(sectionList)):
                    groupList.append(sectionList[c]["text"])

                pairList.append({
                    "y": bboxSegmentList[1],
                    "bbox": bboxSegmentList,
                    "section": sectionList[0]["text"] if len(sectionList) > 0 else "",
                    "group": " / ".join(groupList),
                    "sectionList": sectionList,
                    "row": "",
                    "key": textList[0],
                    "formula": "",
                    "value": " / ".join(textList[1:])
                })

        return {"pairList": pairList, "lineItemList": lineItemList}

    def _paragraphMerge(self, itemList, height, horizontalList):
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

                if self._ruleBetweenCheck(horizontalList, bboxLastList, bboxList):
                    continue

                if itemObject.get("isBoxOption"):
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

    def _referenceKeyCheck(self, itemList, bboxList, height, horizontalList):
        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            if itemList[a]["type"] != "key" or self._overlap(bboxList[0], bboxList[2], bboxOtherList[0], bboxOtherList[2]) <= 0:
                continue

            gap = bboxList[1] - bboxOtherList[3]
            gapBelow = bboxOtherList[1] - bboxList[3]

            if gap >= -height and gap <= height * self.levelFieldGap and self._ruleBetweenCheck(horizontalList, bboxOtherList, bboxList) == False:
                return True

            if gapBelow >= -height and gapBelow <= height * self.levelFieldGap and self._ruleBetweenCheck(horizontalList, bboxList, bboxOtherList) == False:
                return True

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            if itemList[a]["type"] == "key" and bboxOtherList[2] <= bboxList[0] + height * self.levelMargin and bboxList[0] - bboxOtherList[2] <= height * self.levelFieldGap and self._rangeCheck(bboxOtherList, bboxList):
                return True

        return False

    def _referenceRowCheck(self, bboxList, itemList, horizontalList):
        centerY = (bboxList[1] + bboxList[3]) / 2

        for a in range(len(itemList)):
            if itemList[a]["type"] != "row" or itemList[a]["bbox"][0] < bboxList[2]:
                continue

            bandList = self._bandFind(itemList[a]["bbox"], horizontalList)

            if bandList != None and centerY >= bandList[0] and centerY <= bandList[1]:
                return True

        return False

    def _referenceNumberList(self, text):
        resultList = []

        number = ""

        for a in range(len(text) + 1):
            if a < len(text) and unicodedata.category(text[a]) == "Nd":
                number += text[a]

                continue

            if len(number) > 0:
                resultList.append(self._numberValue(number))

                number = ""

            if a < len(text) and unicodedata.category(text[a]) not in ["Pd", "Sm", "Lo"]:
                return []

        return resultList

    def _referenceCheck(self, text, rowNumberList):
        numberList = self._referenceNumberList(text)

        for a in range(len(numberList)):
            if numberList[a] not in rowNumberList:
                return False

        return len(numberList) > 0

    def _digitCount(self, text):
        count = 0

        for a in range(len(text)):
            if unicodedata.category(text[a]) == "Nd":
                count += 1

        return count

    def _keyTextAssign(self, itemList, horizontalList):
        for a in range(len(itemList)):
            if itemList[a]["type"] != "value" or "detectionIndex" not in itemList[a] or self._digitCount(itemList[a]["text"]) > self.countRowDigit or self._referenceRowCheck(itemList[a]["bbox"], itemList, horizontalList) == False:
                continue

            for b in range(len(itemList)):
                if itemList[b]["type"] == "key" and itemList[b].get("detectionIndex") == itemList[a]["detectionIndex"]:
                    itemList[a]["type"] = "key"

                    break

    def _referenceAssign(self, itemList, height, horizontalList):
        rowNumberList = []

        for a in range(len(itemList)):
            if itemList[a]["type"] == "row":
                rowNumberList.append(self._numberValue(self._textClean(itemList[a]["text"])))

        for a in range(len(itemList)):
            if itemList[a]["type"] != "value":
                continue

            text = self._textClean(itemList[a]["text"])

            if self._formulaCheck(text) == False and self._referenceCheck(text, rowNumberList) == False:
                continue

            if self._referenceKeyCheck(itemList, itemList[a]["bbox"], height, horizontalList) and self._referenceRowCheck(itemList[a]["bbox"], itemList, horizontalList):
                itemList[a]["type"] = "formula"

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

    def _sameBoxCheck(self, keyList, itemObject):
        for a in range(len(keyList)):
            if "detectionIndex" in itemObject and keyList[a].get("detectionIndex") == itemObject["detectionIndex"]:
                return True

        return False

    def _cellAboveFind(self, anchorObject, itemList, lineObject, height):
        cell = self._cellFind(anchorObject["bbox"], lineObject)

        if anchorObject["type"] != "value" or cell == None:
            return None

        margin = height * self.levelCellInside

        insideList = []

        for a in range(len(itemList)):
            if itemList[a] is not anchorObject and self._cellFind(itemList[a]["bbox"], lineObject) == cell:
                insideList.append(itemList[a])

        if len(insideList) == 1 and insideList[0]["type"] == "key" and insideList[0]["bbox"][3] <= anchorObject["bbox"][1] + height * self.levelMargin and self._shortUnitCheck(insideList[0], height) == False:
            return insideList[0]

        memberList = []

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            cellOther = self._cellFind(bboxList, lineObject)

            if cellOther == None:
                continue

            if itemList[a] is not anchorObject and cellOther == cell:
                return None

            if itemList[a]["type"] != "value" and cellOther[1] <= cell[0] + margin and cell[0] - cellOther[1] <= margin and cellOther[2] == cell[2] and cellOther[3] == cell[3]:
                return None

            if abs(cellOther[0] - cell[0]) <= margin and abs(cellOther[1] - cell[1]) <= margin and abs(cell[2] - cellOther[3]) <= margin:
                memberList.append(itemList[a])

        if len(memberList) != 1 or memberList[0]["type"] != "key" or self._shortUnitCheck(memberList[0], height):
            return None

        return memberList[0]

    def _keyCollect(self, anchorObject, itemList, lineObject, height):
        keyAboveObject = self._cellAboveFind(anchorObject, itemList, lineObject, height)

        if keyAboveObject != None:
            return [keyAboveObject]

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
        cellKey = None

        for a in range(len(candidateList)):
            itemObject = candidateList[a]

            if itemObject["type"] == "value":
                if self._rangeCheck(itemObject["bbox"], bboxAnchorList) == False:
                    continue

                break

            if itemObject["type"] == "row" and (anchorObject["type"] == "row" or self._rowFind(resultList, anchorObject) != None):
                break

            if anchorObject["type"] == "row" and len(resultList) == 0 and self._wallCount(lineObject["verticalList"], itemObject["bbox"][2] + height * self.levelMargin, bboxAnchorList[0] - height * self.levelMargin, itemObject["bbox"]) > 1:
                break

            if edgeLeft != None and edgeLeft - itemObject["bbox"][2] > height * self.levelKeyReach:
                countWall = self._wallCount(lineObject["verticalList"], itemObject["bbox"][2] + height * self.levelMargin, edgeLeft - height * self.levelMargin, itemObject["bbox"])

                if itemObject["type"] not in ["key", "formula"] or countWall > 1 or (countWall == 0 and self._sameBoxCheck(resultList, itemObject) == False and (anchorObject["type"] != "row" or self._cellFind(itemObject["bbox"], lineObject) == None or self._cellFind(itemObject["bbox"], lineObject) != self._cellFind(resultList[0]["bbox"], lineObject))):
                    break

                if countWall == 1 and anchorObject["type"] != "row" and self._rowFind(resultList, anchorObject) == None and (self._wallCount(lineObject["verticalList"], itemObject["bbox"][2] + height * self.levelMargin, itemObject["bbox"][2] + height * self.levelKeyReach, itemObject["bbox"]) == 0 or self._wallCount(lineObject["verticalList"], edgeLeft - height * self.levelKeyReach, edgeLeft - height * self.levelMargin, itemObject["bbox"]) == 0):
                    break

            if itemObject["type"] == "key":
                cell = self._cellFind(itemObject["bbox"], lineObject)

                if cellKey != None and cell != None and cell[1] <= cellKey[0] + height * self.levelMargin and cell[3] - cell[2] <= cellKey[3] - cellKey[2] + height * self.levelBandSame:
                    break

                if cellKey == None:
                    cellKey = cell

            resultList.append(itemObject)

            if itemObject.get("isRowStart"):
                break

            edgeLeft = itemObject["bbox"][0] if edgeLeft == None else min(edgeLeft, itemObject["bbox"][0])

        return resultList

    def _keyRightCollect(self, anchorObject, itemList, usedList, height, lineObject):
        bboxAnchorList = anchorObject["bbox"]

        itemBest = None

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            if itemList[a] is anchorObject or itemList[a] in usedList or itemList[a]["type"] != "key" or bboxList[0] < bboxAnchorList[2] - height * self.levelMargin or self._rangeCheck(bboxList, bboxAnchorList) == False:
                continue

            if itemBest == None or bboxList[0] < itemBest["bbox"][0]:
                itemBest = itemList[a]

        if itemBest == None or itemBest["bbox"][0] - bboxAnchorList[2] > height * self.levelKeyReach:
            return []

        resultList = [itemBest]

        cell = self._cellFind(itemBest["bbox"], lineObject)

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            if cell == None or itemList[a] is itemBest or itemList[a] is anchorObject or itemList[a] in usedList or itemList[a]["type"] not in ["key", "formula"] or bboxList[0] < itemBest["bbox"][2] - height * self.levelMargin or self._rangeCheck(bboxList, bboxAnchorList) == False or self._cellFind(bboxList, lineObject) != cell:
                continue

            resultList.append(itemList[a])

        return resultList

    def _leftCheck(self, itemObject, keyList, itemList, height, verticalList):
        bboxList = itemObject["bbox"]

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            if itemList[a] is itemObject or itemList[a]["type"] not in ["key", "formula"] or bboxOtherList[2] > bboxList[0] + height * self.levelMargin:
                continue

            if bboxList[0] - bboxOtherList[2] > height * self.levelKeyGap:
                continue

            if self._rangeCheck(bboxOtherList, bboxList) == False:
                continue

            if self._wallCheck(verticalList, bboxOtherList[2] - height * self.levelMargin, bboxList[0] + height * self.levelMargin, bboxList):
                continue

            if itemList[a] not in keyList:
                return False

        return True

    def _keyExtend(self, keyList, itemList, bboxAnchorList, height, horizontalList, rowList, edgeRight, rowObject, verticalList):
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

                    if itemObject["type"] == "formula" and resultList[b]["type"] == "formula" and bboxList[0] >= bboxKeyList[0] and bboxList[0] - bboxKeyList[2] <= height * self.levelUnitGap and self._rangeCheck(bboxKeyList, bboxList):
                        isNear = True

                        break

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

                if self._leftCheck(itemObject, resultList, itemList, height, verticalList) == False:
                    continue

                rowAnchorObject = self._rowAnchor(itemObject, rowList, edgeRight)

                if rowObject != None and rowAnchorObject != None and rowAnchorObject is not rowObject:
                    continue

                resultList.append(itemObject)

                isAdded = True

        return resultList

    def _titleRuleCheck(self, bboxList, bboxAnchorList, horizontalList):
        bboxRowList = [bboxList[0], bboxAnchorList[1], bboxList[2], bboxAnchorList[3]]

        if bboxList[1] >= bboxAnchorList[3]:
            return self._ruleBetweenCheck(horizontalList, bboxRowList, bboxList)

        return self._ruleBetweenCheck(horizontalList, bboxList, bboxRowList)

    def _sectionCollect(self, bboxAnchorList, keyLeft, verticalList, height, lineList, horizontalList):
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

                if distance > height * self.levelSectionGap or bboxList[3] - bboxList[1] < height * self.levelSectionSpan or self._titleRuleCheck(bboxList, bboxAnchorList, horizontalList):
                    continue

                isAbove = bboxList[3] < centerY

                if nearestObject == None or (isAbove and isNearestAbove == False) or (isAbove == isNearestAbove and distance < distanceBest):
                    distanceBest = distance
                    nearestObject = itemObject
                    isNearestAbove = isAbove

            if nearestObject != None:
                sectionList.append(nearestObject)

        sectionList.sort(key=lambda itemObject: itemObject["bbox"][0])

        resultList = []

        for a in range(len(sectionList) - 1, -1, -1):
            if self._wallCount(lineList, sectionList[a]["bbox"][2] + height * self.levelMargin, keyLeft - height * self.levelMargin, bboxAnchorList) <= len(resultList) + 1:
                resultList.insert(0, sectionList[a])

        return resultList

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
        countDigit = 0
        countSpace = 0

        for a in range(len(text)):
            if unicodedata.category(text[a]) not in ["Nd", "Zs"]:
                return False

            if unicodedata.category(text[a]) == "Nd":
                countDigit += 1
            elif a > 0 and unicodedata.category(text[a - 1]) == "Nd":
                countSpace += 1

        return countDigit > 0 and (countSpace == 0 or countSpace * 2 >= countDigit - 1)

    def _pairBuild(self, anchorObject, keyList, verticalList, height, lineList, horizontalList):
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
        unit = ""

        if anchorObject["type"] == "value":
            value = anchorObject["text"].strip()

            if self._digitSpaceCheck(value):
                value = self._digitNormalize(self._textClean(value))

            if "suffix" in anchorObject:
                value = f"{value} {anchorObject['suffix']}"

            if anchorObject.get("isTemplate"):
                value = ""

            unit = anchorObject.get("unit", "")
        else:
            rowTextList.append(anchorObject["text"].strip())

        sectionList = self._sectionCollect(anchorObject["bbox"], keyLeft, verticalList, height, lineList, horizontalList)

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
            "value": value,
            "unit": unit
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

            if anchorObject.get("isTemplate") and pairObject["key"] == "" and pairObject["row"] == "" and pairObject["formula"] == "":
                mergedList.append(pairObject)

                continue

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

    def _pairOrder(self, pairList, lineObject, height):
        rowPairList = []
        otherPairList = []

        for a in range(len(pairList)):
            if pairList[a]["row"] != "" and self._numberValue(self._textClean(pairList[a]["row"])) >= 0:
                rowPairList.append(pairList[a])
            else:
                otherPairList.append(pairList[a])

        rowPairList.sort(key=lambda pairObject: self._numberValue(self._textClean(pairObject["row"])))

        for a in range(1, len(rowPairList) - 1):
            if rowPairList[a]["section"] == "" and rowPairList[a - 1]["section"] == rowPairList[a + 1]["section"]:
                rowPairList[a]["section"] = rowPairList[a - 1]["section"]
        otherPairList.sort(key=lambda pairObject: pairObject["y"])

        isSwap = True

        while isSwap:
            isSwap = False

            for a in range(len(otherPairList) - 1):
                bboxList = self._pairBboxFull(otherPairList[a])
                bboxNextList = self._pairBboxFull(otherPairList[a + 1])

                if bboxNextList[2] <= bboxList[0] and self._rangeCheck(bboxList, bboxNextList):
                    otherPairList[a], otherPairList[a + 1] = otherPairList[a + 1], otherPairList[a]

                    isSwap = True

        if len(rowPairList) == 0:
            return self._sectionContiguous(otherPairList, lineObject, height)

        yStart = rowPairList[0]["y"]

        beforeList = []
        afterList = []

        for a in range(len(otherPairList)):
            if otherPairList[a]["y"] < yStart:
                beforeList.append(otherPairList[a])
            else:
                afterList.append(otherPairList[a])

        return self._sectionContiguous(beforeList, lineObject, height) + rowPairList + self._sectionContiguous(afterList, lineObject, height)

    def _blockAssign(self, pairList, lineObject, height):
        extentList = []

        for a in range(len(pairList)):
            bboxList = self._pairBboxFull(pairList[a])

            cell = self._cellFind(bboxList, lineObject)

            top = bboxList[1] if cell == None else cell[2]
            bottom = bboxList[3] if cell == None else cell[3]

            extent = None

            for b in range(len(lineObject["verticalList"])):
                bboxLineList = lineObject["verticalList"][b]

                if self._overlap(bboxLineList[1], bboxLineList[3], top, bottom) < (bottom - top) * self.levelLineCover:
                    continue

                extent = [bboxLineList[0], bboxLineList[2]] if extent == None else [min(extent[0], bboxLineList[0]), max(extent[1], bboxLineList[2])]

            index = -1

            for b in range(len(extentList)):
                if (extent == None and extentList[b]["extent"] == None) or (extent != None and extentList[b]["extent"] != None and abs(extentList[b]["extent"][0] - extent[0]) <= height * self.levelCellInside and abs(extentList[b]["extent"][1] - extent[1]) <= height * self.levelCellInside):
                    index = b

                    break

            if index < 0:
                extentList.append({"extent": extent, "memberList": []})

                index = len(extentList) - 1

            extentList[index]["memberList"].append({"pair": pairList[a], "top": top, "bottom": bottom})

        bandList = []

        for a in range(len(extentList)):
            memberList = sorted(extentList[a]["memberList"], key=lambda memberObject: memberObject["top"])

            for b in range(len(memberList)):
                if b == 0 or memberList[b]["top"] > bandList[len(bandList) - 1]["bottom"] + height * (self.levelFieldGap if extentList[a]["extent"] == None else self.levelCellInside):
                    bandList.append({"top": memberList[b]["top"], "bottom": memberList[b]["bottom"], "pairList": []})

                bandObject = bandList[len(bandList) - 1]

                bandObject["bottom"] = max(bandObject["bottom"], memberList[b]["bottom"])
                bandObject["pairList"].append(memberList[b]["pair"])

        bandList.sort(key=lambda bandObject: bandObject["top"])

        for a in range(len(bandList)):
            for b in range(len(bandList[a]["pairList"])):
                bandList[a]["pairList"][b]["block"] = a

        return len(bandList)

    def _columnAssign(self, pairList):
        pairSortedList = sorted(pairList, key=lambda pairObject: self._pairBboxFull(pairObject)[0])

        column = 0
        right = None

        for a in range(len(pairSortedList)):
            bboxList = self._pairBboxFull(pairSortedList[a])

            if right != None and bboxList[0] >= right:
                column += 1

            pairSortedList[a]["column"] = column
            pairSortedList[a]["order"] = 0

            right = bboxList[2] if right == None else max(right, bboxList[2])

        if len(pairSortedList) > 1 and column == len(pairSortedList) - 1:
            for a in range(len(pairSortedList)):
                pairSortedList[a]["column"] = 0
                pairSortedList[a]["order"] = a

    def _sectionContiguous(self, pairList, lineObject, height):
        orderList = []

        for a in range(len(pairList)):
            if pairList[a]["section"] not in orderList:
                orderList.append(pairList[a]["section"])

        for a in range(len(orderList)):
            memberList = []

            for b in range(len(pairList)):
                if pairList[b]["section"] == orderList[a]:
                    memberList.append(pairList[b])

            countBlock = self._blockAssign(memberList, lineObject, height)

            for b in range(countBlock):
                blockList = []

                for c in range(len(memberList)):
                    if memberList[c]["block"] == b:
                        blockList.append(memberList[c])

                self._columnAssign(blockList)

        return sorted(pairList, key=lambda pairObject: (orderList.index(pairObject["section"]), pairObject["block"], pairObject["column"], pairObject["order"]))

    def _cellEscape(self, text):
        return text.replace("|", "\\|")

    def _templateZeroMark(self, itemList):
        countObject = {}

        for a in range(len(itemList)):
            font = itemList[a].get("font", "")

            if itemList[a]["type"] == "key" and font != "":
                countObject[font] = countObject.get(font, 0) + len(self._textClean(itemList[a]["text"]))

        fontKey = ""

        for font in countObject:
            if fontKey == "" or countObject[font] > countObject[fontKey]:
                fontKey = font

        if fontKey == "":
            return

        candidateList = []

        isFilled = False

        for a in range(len(itemList)):
            if itemList[a]["type"] != "value":
                continue

            partList = itemList[a].get("partList", [itemList[a]])

            isTemplate = True

            for b in range(len(partList)):
                if partList[b].get("font", "") != fontKey:
                    isTemplate = False

            textValue = self._textClean(itemList[a]["text"])

            if isTemplate == False and self._bareNumberCheck(textValue):
                isFilled = True

            if isTemplate and self._zeroCheck(textValue):
                candidateList.append(itemList[a])

        if isFilled:
            for a in range(len(candidateList)):
                candidateList[a]["isTemplate"] = True

    def _digitNormalize(self, text):
        result = ""

        for a in range(len(text)):
            result += str(unicodedata.digit(text[a])) if unicodedata.category(text[a]) == "Nd" else text[a]

        return result

    def _pairBboxFull(self, pairObject):
        if "bboxFull" in pairObject:
            return pairObject["bboxFull"]

        bboxList = list(self._pairBboxFind(pairObject))

        for a in range(len(pairObject.get("keyList", []))):
            bboxList = self._bboxExpand(bboxList, pairObject["keyList"][a]["bbox"])

        return bboxList

    def _strikeText(self, itemObject, rangeList):
        text = itemObject["text"]

        charList = itemObject.get("charList", [])

        if len(charList) != len(text):
            return f"~~{text.strip()}~~"

        result = ""

        isOpen = False

        for a in range(len(text)):
            center = (charList[a]["start"] + charList[a]["end"]) / 2

            isStrike = False

            for b in range(len(rangeList)):
                if center >= rangeList[b][0] and center <= rangeList[b][1]:
                    isStrike = True

            if isStrike != isOpen and len(text[a].strip()) > 0:
                result += "~~"

                isOpen = isStrike

            result += text[a]

        return f"{result}~~" if isOpen else result

    def _strikeApply(self, itemList, lineObject):
        horizontalList = []

        strikeObject = {}

        for a in range(len(lineObject["horizontalList"])):
            bboxLineList = lineObject["horizontalList"][a]

            centerY = (bboxLineList[1] + bboxLineList[3]) / 2

            cover = 0

            matchList = []

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                band = (bboxList[3] - bboxList[1]) * self.levelStrikeBand

                overlap = self._overlap(bboxLineList[0], bboxLineList[2], bboxList[0], bboxList[2])

                if itemList[b].get("isVertical") or overlap <= 0 or centerY < bboxList[1] + band or centerY > bboxList[3] - band:
                    continue

                cover += overlap

                matchList.append(b)

            if len(matchList) == 0 or cover < (bboxLineList[2] - bboxLineList[0]) * self.levelStrikeCover:
                horizontalList.append(bboxLineList)

                continue

            isGlyph = False

            if len(matchList) == 1:
                charList = self._charPosition(itemList[matchList[0]])

                for b in range(len(charList)):
                    if charList[b]["end"] > charList[b]["start"] and charList[b]["start"] <= bboxLineList[0] and charList[b]["end"] >= bboxLineList[2]:
                        isGlyph = True

            if isGlyph:
                continue

            for b in range(len(matchList)):
                if matchList[b] not in strikeObject:
                    strikeObject[matchList[b]] = []

                strikeObject[matchList[b]].append([bboxLineList[0], bboxLineList[2]])

        resultList = []

        for a in range(len(itemList)):
            itemObject = itemList[a]

            if a in strikeObject:
                itemObject = dict(itemObject)

                itemObject["text"] = self._strikeText(itemObject, strikeObject[a])

            resultList.append(itemObject)

        lineResultObject = dict(lineObject)

        lineResultObject["horizontalList"] = horizontalList

        return {"itemList": resultList, "lineObject": lineResultObject}

    def _skeletonText(self, text):
        result = ""

        for a in range(len(text)):
            if text[a].isdigit() == False and text[a].isspace() == False:
                result += text[a]

        return result

    def _lineStackJoin(self, lineList, height):
        resultList = []

        lineSortedList = sorted(lineList, key=lambda lineObject: lineObject["bbox"][1])

        for a in range(len(lineSortedList)):
            bboxList = lineSortedList[a]["bbox"]

            isJoined = False

            for b in range(len(resultList)):
                bboxOtherList = resultList[b]["bbox"]

                gap = bboxList[1] - bboxOtherList[3]

                if resultList[b]["skeleton"] == lineSortedList[a]["skeleton"] and abs(bboxList[0] - bboxOtherList[0]) <= height * self.levelMargin and abs(bboxList[2] - bboxOtherList[2]) <= height * self.levelMargin and gap >= 0 and gap <= (bboxList[3] - bboxList[1]) * self.levelStackGap:
                    resultList[b]["text"] = f"{resultList[b]['text']} / {lineSortedList[a]['text']}"
                    resultList[b]["bbox"] = self._bboxExpand(bboxOtherList, bboxList)

                    isJoined = True

                    break

            if isJoined == False:
                resultList.append(lineSortedList[a])

        return resultList

    def _keyDuplicateSplit(self, pairList, restList, height):
        countObject = {}

        for a in range(len(pairList)):
            key = self._textClean(pairList[a]["key"])

            if pairList[a]["row"] == "" and pairList[a]["formula"] == "" and len(key) > 0 and self._shortTextUnitCheck(key):
                countObject[key] = countObject.get(key, 0) + 1

        resultList = []
        lineList = []

        for a in range(len(pairList)):
            key = self._textClean(pairList[a]["key"])

            if pairList[a]["row"] != "" or pairList[a]["formula"] != "" or countObject.get(key, 0) < 2:
                resultList.append(pairList[a])

                continue

            lineList.append({"text": f"{pairList[a]['key']} {pairList[a]['value']}", "bbox": self._pairBboxFull(pairList[a]), "skeleton": self._skeletonText(f"{pairList[a]['key']} {pairList[a]['value']}")})

        lineList = self._lineStackJoin(lineList, height)

        restResultList = []

        for a in range(len(restList)):
            bboxList = restList[a]["bbox"]

            isJoined = False

            for b in range(len(lineList)):
                bboxLineList = lineList[b]["bbox"]

                gap = bboxList[0] - bboxLineList[2]

                if gap >= -height * self.levelMargin and gap <= height * self.levelFieldGap and self._overlap(bboxList[1], bboxList[3], bboxLineList[1], bboxLineList[3]) >= min(bboxList[3] - bboxList[1], bboxLineList[3] - bboxLineList[1]) * self.levelParagraphOverlap:
                    lineList[b]["text"] = f"{lineList[b]['text']} | {restList[a]['text']}"
                    lineList[b]["bbox"] = self._bboxExpand(bboxLineList, bboxList)

                    isJoined = True

                    break

            if isJoined == False:
                restResultList.append(restList[a])

        return {"pairList": resultList, "restList": restResultList + lineList}

    def _headerMemberList(self, cell, pairList, height, pairHeader, lineObject):
        memberList = []

        bottom = cell[3]

        bboxPairList = []

        for a in range(len(pairList)):
            bboxList = self._pairBboxFull(pairList[a])

            cellPair = self._cellProbe(bboxList, height, lineObject)

            bboxPairList.append(bboxList if cellPair == None else [bboxList[0], min(bboxList[1], cellPair[2]), bboxList[2], max(bboxList[3], cellPair[3])])

        isAdded = True

        while isAdded:
            isAdded = False

            bottomNext = bottom

            for a in range(len(pairList)):
                bboxList = bboxPairList[a]

                if pairList[a] is pairHeader or pairList[a] in memberList or bboxList[0] < cell[0] - height * self.levelMargin or bboxList[2] > cell[1] + height * self.levelMargin or bboxList[1] < bottom - height * self.levelMargin or bboxList[1] - bottom > height * (self.levelHeaderGap if bottom == cell[3] else self.levelCellInside):
                    continue

                memberList.append(pairList[a])

                bottomNext = max(bottomNext, bboxList[3])

                isAdded = True

            if len(memberList) > 0 and bottom == cell[3]:
                self.countHeaderRow = len(memberList)

            bottom = bottomNext

        return memberList

    def _ruleContinueCheck(self, cell, height, horizontalList):
        margin = height * self.levelCellInside

        for a in range(len(horizontalList)):
            bboxLineList = horizontalList[a]

            centerY = (bboxLineList[1] + bboxLineList[3]) / 2

            if (abs(centerY - cell[2]) <= margin or abs(centerY - cell[3]) <= margin) and bboxLineList[0] <= cell[1] - margin and bboxLineList[2] >= cell[1] + height:
                return True

        return False

    def _groupHeaderAssign(self, pairList, restList, height, lineObject, itemList):
        candidateList = []

        for a in range(len(restList)):
            candidateList.append({"text": restList[a]["text"], "bbox": restList[a]["bbox"], "rest": restList[a], "pair": None})

        for a in range(len(pairList)):
            if pairList[a]["value"] == "" and pairList[a]["row"] == "" and pairList[a]["formula"] == "" and "bboxKey" in pairList[a] and pairList[a].get("isSelfField") != True:
                candidateList.append({"text": pairList[a]["key"], "bbox": pairList[a]["bboxKey"], "rest": None, "pair": pairList[a]})

        cellList = []

        for a in range(len(candidateList)):
            cellList.append(self._cellProbe(candidateList[a]["bbox"], height, lineObject))

        restUsedList = []
        pairUsedList = []

        for a in range(len(candidateList)):
            cell = cellList[a]

            if cell == None or cellList.count(cell) > 1 or self._letterContain(candidateList[a]["text"]) == False or self.textOption in candidateList[a]["text"] or self.textMark in candidateList[a]["text"] or self.reference.sentenceEndCheck(candidateList[a]["text"]):
                continue

            isAlone = True

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                centerX = (bboxList[0] + bboxList[2]) / 2
                centerY = (bboxList[1] + bboxList[3]) / 2

                if centerX > cell[0] and centerX < cell[1] and centerY > cell[2] and centerY < cell[3] and (centerX < candidateList[a]["bbox"][0] or centerX > candidateList[a]["bbox"][2] or centerY < candidateList[a]["bbox"][1] or centerY > candidateList[a]["bbox"][3]):
                    isAlone = False

                    break

            if isAlone == False or self._cellBlockCheck(cell, lineObject) or (candidateList[a]["pair"] != None and self._ruleContinueCheck(cell, height, lineObject["horizontalList"]) and self._cellRightEmptyCheck(cell, height, lineObject, itemList)):
                continue

            self.countHeaderRow = 0

            memberList = self._headerMemberList(cell, pairList, height, candidateList[a]["pair"], lineObject)

            for b in range(len(pairUsedList)):
                if pairUsedList[b] in memberList:
                    memberList.remove(pairUsedList[b])

            if len(memberList) < 2:
                continue

            isSection = len(memberList) > self.countHeaderRow

            if isSection:
                sectionList = []

                for b in range(len(pairList)):
                    if pairList[b] in memberList and pairList[b]["section"] == "":
                        sectionList.append(pairList[b])

                if len(sectionList) > 0:
                    index = pairList.index(sectionList[0])

                    pairList = pairList[0:index] + sectionList + self._restRemove(pairList[index:], sectionList)

            for b in range(len(memberList)):
                if isSection and memberList[b]["section"] == "":
                    memberList[b]["section"] = candidateList[a]["text"]
                else:
                    memberList[b]["group"] = candidateList[a]["text"] if memberList[b]["group"] == "" else f"{candidateList[a]['text']} / {memberList[b]['group']}"

            if candidateList[a]["rest"] != None:
                restUsedList.append(candidateList[a]["rest"])
            else:
                pairUsedList.append(candidateList[a]["pair"])

            isBlock = isSection == False

            for b in range(len(memberList)):
                if "block" not in memberList[b] or memberList[b]["block"] != memberList[0].get("block"):
                    isBlock = False

            if isBlock:
                self._columnAssign(memberList)

        return {"pairList": self._restRemove(pairList, pairUsedList), "restList": self._restRemove(restList, restUsedList)}

    def _sectionInherit(self, pairList):
        extentList = []

        for a in range(len(pairList)):
            if len(pairList[a]["sectionList"]) == 0:
                continue

            bboxList = self._pairBboxFull(pairList[a])

            isAdded = False

            for b in range(len(extentList)):
                if extentList[b]["sectionList"][0] is pairList[a]["sectionList"][0]:
                    extentList[b]["right"] = max(extentList[b]["right"], bboxList[2])

                    isAdded = True

                    break

            if isAdded == False:
                extentList.append({"sectionList": pairList[a]["sectionList"], "section": pairList[a]["section"], "right": bboxList[2]})

        for a in range(len(pairList)):
            if len(pairList[a]["sectionList"]) > 0:
                continue

            bboxList = self._pairBboxFull(pairList[a])

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            extentBest = None

            for b in range(len(extentList)):
                bboxTitleList = extentList[b]["sectionList"][0]["bbox"]

                if centerY < bboxTitleList[1] or centerY > bboxTitleList[3] or centerX < bboxTitleList[2] or centerX > extentList[b]["right"]:
                    continue

                if extentBest == None or bboxTitleList[2] > extentBest["sectionList"][0]["bbox"][2]:
                    extentBest = extentList[b]

            if extentBest != None:
                pairList[a]["section"] = extentBest["section"]
                pairList[a]["sectionList"] = [extentBest["sectionList"][0]]

    def _ruleSpanCheck(self, horizontalList, top, height, left, right):
        margin = height * self.levelMargin

        for a in range(len(horizontalList)):
            bboxLineList = horizontalList[a]

            if abs(bboxLineList[3] - top) <= margin and bboxLineList[0] <= left + margin and bboxLineList[2] >= right - margin:
                return True

        return False

    def _unitCaptionAssign(self, restList, height, pairList, lineObject):
        resultList = []

        for a in range(len(restList)):
            bboxList = restList[a]["bbox"]

            if bboxList[3] - bboxList[1] > height * self.levelUnitSize or self.reference.captionCheck(restList[a]["text"], self.reference.currencyList) == False:
                resultList.append(restList[a])

                continue

            centerX = (bboxList[0] + bboxList[2]) / 2

            rowList = []

            for b in range(len(pairList)):
                if "anchor" not in pairList[b] or pairList[b]["row"] == "" or pairList[b]["unit"] != "":
                    continue

                rowObject = self._rowFind(pairList[b]["keyList"], pairList[b]["anchor"])

                if rowObject == None:
                    continue

                bboxAnchorList = rowObject["bbox"]

                bandList = self._bandFind(bboxAnchorList, lineObject["horizontalList"])

                if bandList == None or bandList[0] < bboxList[3] - height * self.levelMargin or self._ruleSpanCheck(lineObject["horizontalList"], bandList[0], height, min(bboxAnchorList[0], centerX), max(bboxAnchorList[2], centerX)) == False or self._cellFind([centerX - 1, bboxAnchorList[1], centerX + 1, bboxAnchorList[3]], lineObject) == None:
                    continue

                rowList.append({"pair": pairList[b], "band": bandList})

            rowList.sort(key=lambda rowObject: rowObject["band"][0])

            bottom = bboxList[3]

            reach = height * self.levelUnitAbove

            isAssigned = False

            for b in range(len(rowList)):
                if rowList[b]["band"][0] - bottom > reach:
                    break

                rowList[b]["pair"]["unit"] = restList[a]["text"].strip()

                bottom = rowList[b]["band"][1]

                reach = height * self.levelMargin

                isAssigned = True

            if isAssigned == False:
                resultList.append(restList[a])

        return resultList

    def _combList(self, verticalList, itemList, height):
        groupList = []

        margin = height * self.levelCellInside

        wallList = sorted(verticalList, key=lambda bboxList: bboxList[0])

        for a in range(len(wallList)):
            bboxList = wallList[a]

            if bboxList[3] - bboxList[1] > height * self.levelCellLabel:
                continue

            isAdded = False

            for b in range(len(groupList)):
                bboxLastList = groupList[b][len(groupList[b]) - 1]

                if abs(bboxLastList[1] - bboxList[1]) <= margin and abs(bboxLastList[3] - bboxList[3]) <= margin and bboxList[0] - bboxLastList[2] <= height * self.levelModuleBoxSize:
                    groupList[b].append(bboxList)

                    isAdded = True

                    break

            if isAdded == False:
                groupList.append([bboxList])

        resultList = []

        for a in range(len(groupList)):
            if len(groupList[a]) < self.countMatrixMinimum:
                continue

            bboxCombList = [groupList[a][0][0], groupList[a][0][1], groupList[a][len(groupList[a]) - 1][2], groupList[a][0][3]]

            isEmpty = True

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                if self._overlap(bboxList[0], bboxList[2], bboxCombList[0], bboxCombList[2]) > 0 and self._overlap(bboxList[1], bboxList[3], bboxCombList[1], bboxCombList[3]) > 0:
                    isEmpty = False

                    break

            if isEmpty:
                resultList.append(bboxCombList)

        return resultList

    def _lineWrapRoomCheck(self, bboxList, itemList, lineObject, height):
        memberList = []

        right = None

        for a in range(len(itemList)):
            bboxItemList = itemList[a]["bbox"]

            centerX = (bboxItemList[0] + bboxItemList[2]) / 2
            centerY = (bboxItemList[1] + bboxItemList[3]) / 2

            if centerX > bboxList[0] and centerX < bboxList[2] and centerY > bboxList[1] and centerY < bboxList[3]:
                memberList.append(itemList[a])
            elif bboxItemList[0] >= bboxList[2] and self._overlap(bboxItemList[1], bboxItemList[3], bboxList[1], bboxList[3]) > 0 and (right == None or bboxItemList[0] < right):
                right = bboxItemList[0]

        for a in range(len(lineObject["verticalList"])):
            bboxLineList = lineObject["verticalList"][a]

            if bboxLineList[0] >= bboxList[2] and self._overlap(bboxLineList[1], bboxLineList[3], bboxList[1], bboxList[3]) > 0 and (right == None or bboxLineList[0] < right):
                right = bboxLineList[0]

        rowList = self._cellLineGroup(sorted(memberList, key=lambda itemObject: itemObject["bbox"][1]))

        if right == None or len(rowList) < 2:
            return False

        widthLast = 0

        for a in range(len(rowList[len(rowList) - 1])):
            bboxItemList = rowList[len(rowList) - 1][a]["bbox"]

            widthLast += bboxItemList[2] - bboxItemList[0]

        room = right - bboxList[2]

        return room >= height * self.levelKeyReach and room >= widthLast + (bboxList[2] - bboxList[0])

    def _lineUnderlineCheck(self, bboxList, itemList, lineObject, height):
        for a in range(len(lineObject["horizontalList"])):
            bboxLineList = lineObject["horizontalList"][a]

            centerY = (bboxLineList[1] + bboxLineList[3]) / 2

            if bboxLineList[0] < bboxList[2] - height * self.levelMargin or bboxLineList[0] - bboxList[2] > height * self.levelKeyGap or abs(centerY - bboxList[3]) > height * self.levelCellInside:
                continue

            isFree = True

            for b in range(len(lineObject["verticalList"])):
                bboxWallList = lineObject["verticalList"][b]

                centerX = (bboxWallList[0] + bboxWallList[2]) / 2

                if bboxWallList[1] <= centerY + height * self.levelMargin and bboxWallList[3] >= centerY - height * self.levelMargin and (abs(centerX - bboxLineList[0]) <= height * self.levelMargin or abs(centerX - bboxLineList[2]) <= height * self.levelMargin):
                    isFree = False

                    break

            for b in range(len(itemList)):
                bboxItemList = itemList[b]["bbox"]

                if self._overlap(bboxItemList[0], bboxItemList[2], bboxLineList[0], bboxLineList[2]) > 0 and self._overlap(bboxItemList[1], bboxItemList[3], bboxList[1], centerY) > 0:
                    isFree = False

                    break

            if isFree:
                return True

        return False

    def _lineFieldBuild(self, restList, pairList, itemList, lineObject, height):
        combList = self._combList(lineObject["verticalList"], itemList, height)

        usedList = []

        for a in range(len(combList)):
            bboxCombList = combList[a]

            restObject = None

            for b in range(len(restList)):
                bboxList = restList[b]["bbox"]

                if restList[b] in usedList or "lineList" in restList[b] or self._letterContain(restList[b]["text"]) == False or self.textOption in restList[b]["text"] or self.textMark in restList[b]["text"]:
                    continue

                if self._overlap(bboxList[1], bboxList[3], bboxCombList[1], bboxCombList[3]) <= 0 or bboxList[0] >= bboxCombList[0] or bboxCombList[0] - bboxList[2] > height * self.levelKeyGap:
                    continue

                if restObject == None or bboxList[2] > restObject["bbox"][2]:
                    restObject = restList[b]

            if restObject != None:
                usedList.append(restObject)

        for a in range(len(restList)):
            if restList[a] in usedList or "lineList" in restList[a] or restList[a].get("isOutside") or restList[a].get("isJoin") or self._letterContain(restList[a]["text"]) == False or self.textOption in restList[a]["text"] or self.textMark in restList[a]["text"]:
                continue

            if self._lineWrapRoomCheck(restList[a]["bbox"], itemList, lineObject, height):
                usedList.append(restList[a])

        removeList = []

        for a in range(len(restList)):
            if restList[a] in usedList or restList[a] in removeList or "lineList" in restList[a] or restList[a].get("isOutside") or restList[a].get("isJoin") or self._letterContain(restList[a]["text"]) == False or self.textOption in restList[a]["text"] or self.textMark in restList[a]["text"]:
                continue

            if self._lineUnderlineCheck(restList[a]["bbox"], itemList, lineObject, height) == False:
                continue

            fieldObject = dict(restList[a])

            isFound = True

            while isFound:
                isFound = False

                for b in range(len(restList)):
                    bboxList = restList[b]["bbox"]

                    gap = fieldObject["bbox"][1] - bboxList[3]

                    if restList[b] is restList[a] or restList[b] in usedList or restList[b] in removeList or "lineList" in restList[b] or restList[b].get("isJoin") or abs(bboxList[0] - fieldObject["bbox"][0]) > height * self.levelMargin or gap < -height * self.levelLineGap or gap > height * self.levelOptionLineGap or self.textOption in restList[b]["text"] or self.textMark in restList[b]["text"]:
                        continue

                    fieldObject["text"] = self._textAppend(restList[b]["text"], fieldObject["text"])
                    fieldObject["bbox"] = self._bboxExpand(fieldObject["bbox"], bboxList)

                    removeList.append(restList[b])

                    isFound = True

                    break

            removeList.append(restList[a])

            usedList.append(fieldObject)

        for a in range(len(usedList)):
            bboxList = usedList[a]["bbox"]

            pairObject = {"y": bboxList[1], "bbox": bboxList, "bboxKey": bboxList, "bboxFull": bboxList, "section": "", "group": "", "sectionList": [], "row": "", "key": self._spaceNormalize(usedList[a]["text"]), "formula": "", "value": "", "isSelfField": True}

            index = len(pairList)

            for b in range(len(pairList)):
                bboxPairList = self._pairBboxFull(pairList[b])

                if bboxPairList[1] > bboxList[1]:
                    index = b

                    break

            if index > 0:
                pairObject["section"] = pairList[index - 1]["section"]
                pairObject["sectionList"] = pairList[index - 1]["sectionList"]

                if "column" in pairList[index - 1]:
                    pairObject["column"] = pairList[index - 1]["column"]

                if "block" in pairList[index - 1]:
                    pairObject["block"] = pairList[index - 1]["block"]

            pairList.insert(index, pairObject)

        return self._restRemove(restList, usedList + removeList)

    def _rowNoteAssign(self, pairList, restList, horizontalList):
        resultList = list(pairList)

        restResultList = []

        for a in range(len(restList)):
            bboxList = restList[a]["bbox"]

            centerY = (bboxList[1] + bboxList[3]) / 2

            pairBest = None
            rowRight = None

            for b in range(len(pairList)):
                if "anchor" not in pairList[b] or pairList[b]["row"] == "":
                    continue

                rowObject = self._rowFind(pairList[b]["keyList"], pairList[b]["anchor"])

                if rowObject == None or rowObject["bbox"][2] > bboxList[0]:
                    continue

                rightColumn = 0

                for c in range(len(pairList)):
                    if "anchor" not in pairList[c]:
                        continue

                    rowOtherObject = self._rowFind(pairList[c]["keyList"], pairList[c]["anchor"])

                    if rowOtherObject != None and self._overlap(rowOtherObject["bbox"][0], rowOtherObject["bbox"][2], rowObject["bbox"][0], rowObject["bbox"][2]) > 0:
                        rightColumn = max(rightColumn, self._pairBboxFull(pairList[c])[2])

                if bboxList[0] >= rightColumn:
                    continue

                bandList = self._bandFind(rowObject["bbox"], horizontalList)

                if bandList == None or centerY < bandList[0] or centerY > bandList[1]:
                    continue

                if rowRight == None or rowObject["bbox"][2] > rowRight:
                    rowRight = rowObject["bbox"][2]
                    pairBest = pairList[b]

            if pairBest == None:
                restResultList.append(restList[a])

                continue

            resultList.insert(resultList.index(pairBest) + 1, {
                "y": bboxList[1],
                "bbox": bboxList,
                "bboxFull": bboxList,
                "section": pairBest["section"],
                "sectionList": pairBest["sectionList"],
                "group": pairBest["group"],
                "column": pairBest.get("column", 0),
                "block": pairBest.get("block", 0),
                "row": pairBest["row"],
                "key": f"{pairBest['key']} / {restList[a]['text']}",
                "formula": "",
                "value": "",
                "unit": pairBest.get("unit", "")
            })

        return {"pairList": resultList, "restList": restResultList}

    def _keyQualifierAssign(self, pairList, height):
        for a in range(len(pairList)):
            key = self._textClean(pairList[a]["key"])

            if len(key) < 3 or unicodedata.category(key[0]) != "Ps" or unicodedata.category(key[-1]) != "Pe" or self._bracketCount(key[1:-1]) != 0:
                continue

            bboxList = self._pairBboxFull(pairList[a])

            pairBest = None

            for b in range(len(pairList)):
                bboxOtherList = self._pairBboxFull(pairList[b])

                if b == a or pairList[b]["key"] == "" or abs(bboxOtherList[0] - bboxList[0]) > height or bboxOtherList[1] < bboxList[3] - height * self.levelMargin or bboxOtherList[1] - bboxList[3] > height * self.levelQualifierGap:
                    continue

                if pairBest == None or bboxOtherList[1] < self._pairBboxFull(pairBest)[1]:
                    pairBest = pairList[b]

            if pairBest != None:
                pairList[a]["key"] = f"{pairBest['key']} {pairList[a]['key']}"

    def _captionCollect(self, itemBeforeList, itemList):
        resultList = []

        for a in range(len(itemBeforeList)):
            isUsed = True

            for b in range(len(itemList)):
                if itemList[b] is itemBeforeList[a]:
                    isUsed = False

                    break

            textCaption = self._textClean(itemBeforeList[a]["text"])

            if isUsed and itemBeforeList[a]["type"] == "key" and len(textCaption) > 0 and textCaption not in resultList:
                resultList.append(textCaption)

        return resultList

    def _captionSmallCheck(self, itemObject, height, lineObject):
        bboxList = itemObject["bbox"]

        return itemObject["type"] == "key" and bboxList[3] - bboxList[1] <= height * self.levelUnitSize and self._cellFind(bboxList, lineObject) != None

    def _captionLetterJoin(self, itemList, height, lineObject):
        itemSortedList = sorted(itemList, key=lambda itemObject: itemObject["bbox"][0])

        removeList = []
        addList = []

        for a in range(len(itemSortedList)):
            itemObject = itemSortedList[a]

            textItem = self._textClean(itemObject["text"])

            if itemObject in removeList or len(textItem) != 1 or self._captionSmallCheck(itemObject, height, lineObject) == False or self.reference.dateLetterCheck(textItem) == False:
                continue

            chainList = [itemObject]

            for b in range(a + 1, len(itemSortedList)):
                candidateObject = itemSortedList[b]

                bboxLastList = chainList[len(chainList) - 1]["bbox"]

                if candidateObject in removeList or self._rangeCheck(candidateObject["bbox"], bboxLastList) == False or self._captionSmallCheck(candidateObject, height, lineObject) == False:
                    continue

                if self._textClean(candidateObject["text"]) != textItem or candidateObject["bbox"][0] - bboxLastList[2] > height * self.levelLetterGap:
                    break

                chainList.append(candidateObject)

            if len(chainList) < 2:
                continue

            joinObject = dict(itemObject)

            joinObject["text"] = textItem * len(chainList)
            joinObject["bbox"] = list(itemObject["bbox"])
            joinObject["charList"] = []

            for b in range(len(chainList)):
                joinObject["bbox"] = self._bboxExpand(joinObject["bbox"], chainList[b]["bbox"])

                removeList.append(chainList[b])

            addList.append(joinObject)

        resultList = []

        for a in range(len(itemList)):
            if itemList[a] not in removeList:
                resultList.append(itemList[a])

        return resultList + addList

    def _captionRunList(self, itemList, height, lineObject):
        candidateList = []

        for a in range(len(itemList)):
            if self._captionSmallCheck(itemList[a], height, lineObject) and self.reference.dateLetterCheck(itemList[a]["text"]):
                candidateList.append(itemList[a])

        candidateList.sort(key=lambda itemObject: itemObject["bbox"][0])

        runList = []

        for a in range(len(candidateList)):
            bboxList = candidateList[a]["bbox"]

            isAdded = False

            for b in range(len(runList)):
                bboxLastList = runList[b][len(runList[b]) - 1]["bbox"]

                if self._rangeCheck(bboxList, bboxLastList) == False:
                    continue

                isBetween = self._wallCount(lineObject["verticalList"], bboxLastList[2], bboxList[0], bboxLastList) > 0

                for c in range(len(itemList)):
                    bboxOtherList = itemList[c]["bbox"]

                    centerX = (bboxOtherList[0] + bboxOtherList[2]) / 2

                    if itemList[c] not in candidateList and centerX > bboxLastList[2] and centerX < bboxList[0] and self._rangeCheck(bboxOtherList, bboxLastList):
                        isBetween = True

                        break

                if isBetween == False:
                    runList[b].append(candidateList[a])

                    isAdded = True

                    break

            if isAdded == False:
                runList.append([candidateList[a]])

        return runList

    def _captionRemove(self, itemList, height, lineObject, captionList):
        removeList = []

        tokenList = captionList + self.reference.dateCaptionList

        for a in range(len(itemList)):
            if self._captionSmallCheck(itemList[a], height, lineObject) and (self.reference.captionCheck(itemList[a]["text"], tokenList) or self.reference.datePatternCheck(itemList[a]["text"])):
                removeList.append(itemList[a])

        runList = self._captionRunList(self._restRemove(itemList, removeList), height, lineObject)

        for a in range(len(runList)):
            textList = []

            for b in range(len(runList[a])):
                textList.append(runList[a][b]["text"])

            if self.reference.datePatternCheck(" ".join(textList)):
                removeList = removeList + runList[a]

        return self._restRemove(itemList, removeList)

    def _textMarkPart(self, itemObject, indexStart, indexEnd):
        text = itemObject["text"]

        charList = self._charPosition(itemObject)

        if len(charList) != len(text):
            charList = self._charPosition({"text": text, "bbox": itemObject["bbox"]})

        indexFirst = indexStart
        indexLast = indexEnd

        while indexFirst < indexLast and text[indexFirst].isspace():
            indexFirst += 1

        while indexLast > indexFirst and text[indexLast - 1].isspace():
            indexLast -= 1

        if indexFirst == indexLast:
            return None

        bboxList = itemObject["bbox"]

        partObject = dict(itemObject)

        partObject["text"] = text[indexFirst:indexLast]
        partObject["bbox"] = [charList[indexFirst]["start"], bboxList[1], charList[indexLast - 1]["end"], bboxList[3]]
        partObject["charList"] = charList[indexFirst:indexLast]

        return partObject

    def _textMarkApply(self, itemList, height, lineObject):
        tokenObject = {}
        cellObject = {}

        for a in range(len(itemList)):
            tokenList = self.reference.markFind(itemList[a]["text"])

            if len(tokenList) > 0:
                tokenObject[a] = tokenList
                cellObject[a] = self._cellFind(itemList[a]["bbox"], lineObject)

        resultList = []

        soloList = []

        for a in range(len(itemList)):
            if a not in tokenObject:
                resultList.append(itemList[a])

                continue

            groupList = []

            for b in tokenObject:
                if cellObject[b] == cellObject[a] and self._rangeCheck(itemList[b]["bbox"], itemList[a]["bbox"]):
                    groupList = groupList + tokenObject[b]

            if self.reference.markValidCheck(groupList) == False:
                resultList.append(itemList[a])

                continue

            tokenList = tokenObject[a]

            prefixObject = self._textMarkPart(itemList[a], 0, tokenList[0]["index"])

            if prefixObject != None:
                resultList.append(prefixObject)

            for b in range(len(tokenList)):
                indexEnd = tokenList[b + 1]["index"] if b + 1 < len(tokenList) else len(itemList[a]["text"])

                partObject = self._textMarkPart(itemList[a], tokenList[b]["index"] + tokenList[b]["length"], indexEnd)

                if partObject == None:
                    soloList.append({"bbox": itemList[a]["bbox"], "isMark": tokenList[b]["isMark"]})

                    continue

                partObject["isOption"] = True

                if tokenList[b]["isMark"]:
                    partObject["isMark"] = True

                resultList.append(partObject)

        for a in range(len(soloList)):
            bboxList = soloList[a]["bbox"]

            itemBest = None

            for b in range(len(resultList)):
                bboxOtherList = resultList[b]["bbox"]

                gap = bboxOtherList[0] - bboxList[2]

                if resultList[b].get("isOption") or self._rangeCheck(bboxOtherList, bboxList) == False or gap < -height * self.levelMargin or gap > height * self.levelKeyGap:
                    continue

                if itemBest == None or bboxOtherList[0] < itemBest["bbox"][0]:
                    itemBest = resultList[b]

            if itemBest != None:
                itemBest["isOption"] = True

                if soloList[a]["isMark"]:
                    itemBest["isMark"] = True

        return resultList

    def _lineColumnPair(self, lineItemList, pairList, height, verticalList, lineObject, pairResultList):
        coupleList = []

        rowUsedList = []

        for a in range(len(lineItemList)):
            if lineItemList[a] in rowUsedList:
                continue

            rowList = []

            for b in range(len(lineItemList)):
                if lineItemList[b]["band"] == lineItemList[a]["band"] and self._rangeCheck(lineItemList[b]["bbox"], lineItemList[a]["bbox"]):
                    rowList.append(lineItemList[b])

            rowUsedList = rowUsedList + rowList

            rowList.sort(key=lambda lineObjectRow: lineObjectRow["bbox"][0])

            isFree = len(rowList) % 2 == 0

            for b in range(len(rowList)):
                if self._cellFind(rowList[b]["bbox"], lineObject) != None:
                    isFree = False

            if isFree == False:
                continue

            for b in range(0, len(rowList), 2):
                if rowList[b + 1]["bbox"][0] - rowList[b]["bbox"][2] > height * self.levelLineJoin and self._wallCount(lineObject["verticalList"], rowList[b]["bbox"][2], rowList[b + 1]["bbox"][0], rowList[b]["bbox"]) == 0:
                    coupleList.append({"key": rowList[b], "value": rowList[b + 1], "row": rowList})

        evidenceList = []

        for a in range(len(coupleList)):
            evidenceList.append({"couple": coupleList[a], "keyX": coupleList[a]["key"]["bbox"][0], "valueX": coupleList[a]["value"]["bbox"][0], "y": coupleList[a]["key"]["bbox"][1]})

        alignedList = []

        for a in range(len(pairList)):
            if "anchor" not in pairList[a] or len(pairList[a]["keyList"]) == 0:
                continue

            keyX = pairList[a]["keyList"][0]["bbox"][0]

            for b in range(len(pairList[a]["keyList"])):
                keyX = min(keyX, pairList[a]["keyList"][b]["bbox"][0])

            evidenceList.append({"couple": None, "keyX": keyX, "valueX": pairList[a]["anchor"]["bbox"][0], "y": pairList[a]["anchor"]["bbox"][1]})

        usedList = []

        for a in range(len(coupleList)):
            keyObject = coupleList[a]["key"]
            valueObject = coupleList[a]["value"]

            isAligned = False

            for b in range(len(evidenceList)):
                if evidenceList[b]["couple"] is coupleList[a]:
                    continue

                if abs(evidenceList[b]["keyX"] - keyObject["bbox"][0]) <= height * self.levelCellInside and abs(evidenceList[b]["valueX"] - valueObject["bbox"][0]) <= height * self.levelCellInside and abs(evidenceList[b]["y"] - keyObject["bbox"][1]) <= height * self.levelSectionGap:
                    isAligned = True

                    break

            if isAligned:
                alignedList.append(coupleList[a])

        for a in range(len(coupleList)):
            keyObject = coupleList[a]["key"]
            valueObject = coupleList[a]["value"]

            isAligned = coupleList[a] in alignedList

            for b in range(len(alignedList)):
                if isAligned == False and alignedList[b]["row"] is coupleList[a]["row"] and abs((alignedList[b]["value"]["bbox"][0] - alignedList[b]["key"]["bbox"][0]) - (valueObject["bbox"][0] - keyObject["bbox"][0])) <= height * self.levelCellInside:
                    isAligned = True

            if isAligned == False or keyObject in usedList or valueObject in usedList:
                continue

            self._cellPairAppend([keyObject], [valueObject], height, verticalList, lineObject, pairResultList)

            usedList.append(keyObject)
            usedList.append(valueObject)

        return self._restRemove(lineItemList, usedList)

    def _tableBuild(self, pairList):
        tableList = []

        for a in range(len(pairList)):
            bboxList = self._pairBboxFull(pairList[a])

            if a == 0 or pairList[a]["section"] != pairList[a - 1]["section"] or pairList[a].get("column", 0) != pairList[a - 1].get("column", 0) or pairList[a].get("block", 0) != pairList[a - 1].get("block", 0):
                tableList.append({"pairList": [], "bboxList": [], "bbox": list(bboxList), "isOrdered": True, "lineObject": {}, "beforeList": [], "isHeading": a == 0 or pairList[a]["section"] != pairList[a - 1]["section"]})

                if len(pairList[a]["sectionList"]) > 0:
                    tableList[len(tableList) - 1]["bbox"] = self._bboxExpand(bboxList, pairList[a]["sectionList"][0]["bbox"])

            tableObject = tableList[len(tableList) - 1]

            if len(tableObject["bboxList"]) > 0 and bboxList[1] < tableObject["bboxList"][len(tableObject["bboxList"]) - 1][1]:
                tableObject["isOrdered"] = False

            tableObject["pairList"].append(pairList[a])
            tableObject["bboxList"].append(bboxList)
            tableObject["bbox"] = self._bboxExpand(tableObject["bbox"], bboxList)

        return tableList

    def _tableLineAssign(self, tableList, restList):
        resultList = []

        right = 0

        for a in range(len(tableList)):
            right = max(right, tableList[a]["bbox"][2])

        for a in range(len(restList)):
            bboxList = restList[a]["bbox"]

            isAssigned = False

            centerY = (bboxList[1] + bboxList[3]) / 2

            indexSection = -1

            for b in range(len(tableList)):
                sectionList = tableList[b]["pairList"][0]["sectionList"]

                if bboxList[0] >= right or len(sectionList) == 0 or sectionList[0]["bbox"][1] > centerY or sectionList[0]["bbox"][3] < centerY or sectionList[0]["bbox"][2] > bboxList[0]:
                    continue

                if indexSection < 0 or sectionList[0]["bbox"][2] > tableList[indexSection]["pairList"][0]["sectionList"][0]["bbox"][2]:
                    indexSection = b

            for b in range(len(tableList)):
                tableObject = tableList[b]

                if indexSection >= 0 and b != indexSection:
                    continue

                if indexSection < 0 and (bboxList[1] >= tableObject["bbox"][3] or self._overlap(bboxList[0], bboxList[2], tableObject["bbox"][0], tableObject["bbox"][2]) <= 0):
                    continue

                if bboxList[3] <= tableObject["bbox"][1]:
                    tableObject["beforeList"].append(restList[a])

                    isAssigned = True

                    break

                index = len(tableObject["pairList"])

                if tableObject["isOrdered"] and (len(self._textClean(restList[a]["text"])) > self.countLineSplit or bboxList[1] < tableObject["bboxList"][0][1]):
                    for c in range(len(tableObject["bboxList"])):
                        if tableObject["bboxList"][c][1] > bboxList[1]:
                            index = c

                            break

                if index not in tableObject["lineObject"]:
                    tableObject["lineObject"][index] = []

                tableObject["lineObject"][index].append(restList[a])

                isAssigned = True

                break

            if isAssigned == False:
                resultList.append(restList[a])

        return resultList

    def _tableColumnList(self, pairList):
        nameList = ["group", "row", "key", "formula", "value", "unit"]

        resultList = []

        for a in range(len(nameList)):
            isFilled = nameList[a] in ["key", "value"]

            for b in range(len(pairList)):
                if pairList[b].get(nameList[a], "") != "":
                    isFilled = True

            if isFilled:
                resultList.append(nameList[a])

        return resultList

    def _tableWrite(self, pairList, restList):
        tableList = self._tableBuild(pairList)

        restList = self._tableLineAssign(tableList, restList)

        lineList = []

        for a in range(len(tableList)):
            tableObject = tableList[a]

            for b in range(len(tableObject["beforeList"])):
                self._restWrite(tableObject["beforeList"][b], lineList)

            if len(tableObject["beforeList"]) > 0:
                lineList.append("")

            if tableObject["pairList"][0]["section"] != "" and tableObject["isHeading"]:
                lineList = lineList + [f"### {tableObject['pairList'][0]['section']}", ""]

            isHeader = True

            for b in range(len(tableObject["pairList"]) + 1):
                if b in tableObject["lineObject"]:
                    if isHeader == False:
                        lineList.append("")

                    for c in range(len(tableObject["lineObject"][b])):
                        self._restWrite(tableObject["lineObject"][b][c], lineList)

                    lineList.append("")

                    isHeader = True

                if b == len(tableObject["pairList"]):
                    break

                if isHeader:
                    indexEnd = len(tableObject["pairList"])

                    for c in range(b + 1, len(tableObject["pairList"])):
                        if c in tableObject["lineObject"]:
                            indexEnd = c

                            break

                    columnList = self._tableColumnList(tableObject["pairList"][b:indexEnd])

                    lineList = lineList + [f"| {' | '.join(columnList)} |", f"|{' --- |' * len(columnList)}"]

                    isHeader = False

                cellList = []

                for c in range(len(columnList)):
                    cellList.append(self._cellEscape(self._spaceNormalize(tableObject["pairList"][b].get(columnList[c], ""))))

                lineList.append(f"| {' | '.join(cellList)} |")

            if isHeader == False:
                lineList.append("")

        for a in range(len(restList)):
            self._restWrite(restList[a], lineList)

        return lineList

    def _leaderStrip(self, itemList):
        resultList = []

        for a in range(len(itemList)):
            textItem = itemList[a]["text"]

            indexEnd = len(textItem)

            countDot = 0

            while indexEnd > 0 and (textItem[indexEnd - 1].isspace() or unicodedata.category(textItem[indexEnd - 1]) == "Po" and textItem[indexEnd - 1] in self.reference.leaderList):
                if textItem[indexEnd - 1].isspace() == False:
                    countDot += 1

                indexEnd -= 1

            isPeriod = True

            for b in range(indexEnd, len(textItem)):
                if textItem[b].isspace() == False and textItem[b] != self.reference.leaderList[0]:
                    isPeriod = False

            if countDot == 0 or itemList[a].get("fieldIndex", 0) != 0 or (countDot < self.countLeaderMinimum and (isPeriod == False or (indexEnd > 0 and textItem[indexEnd - 1].isspace() == False and textItem[indexEnd:].strip() == textItem[indexEnd:indexEnd + countDot]))):
                resultList.append(itemList[a])

                continue

            partObject = self._textMarkPart(itemList[a], 0, indexEnd)

            if partObject != None:
                resultList.append(partObject)

        return resultList

    def _rowIdCheck(self, textItem):
        if len(textItem) == 0 or len(textItem) > self.countRowId:
            return False

        isDigit = False

        for a in range(len(textItem)):
            category = unicodedata.category(textItem[a])

            if category == "Nd":
                isDigit = True
            elif category[0] != "L":
                return False

        return isDigit

    def _rowBoxMark(self, itemList, height, lineObject):
        boxList = []
        cellList = []

        for a in range(len(itemList)):
            cell = self._cellFind(itemList[a]["bbox"], lineObject)

            if cell != None and cell[1] - cell[0] <= height * self.levelCellLabel and self._rowIdCheck(self._textClean(itemList[a]["text"])):
                boxList.append(itemList[a])

                cellList.append(cell)

        removeList = []
        addList = []
        tokenList = []

        for a in range(len(boxList)):
            bboxList = boxList[a]["bbox"]

            textId = self._textClean(boxList[a]["text"])

            left = None

            for b in range(len(boxList)):
                if b != a and boxList[b]["bbox"][2] <= bboxList[0] and self._rangeCheck(boxList[b]["bbox"], bboxList) and (left == None or boxList[b]["bbox"][2] > left):
                    left = boxList[b]["bbox"][2]

            rowList = []

            for b in range(len(itemList)):
                bboxOtherList = itemList[b]["bbox"]

                centerY = (bboxOtherList[1] + bboxOtherList[3]) / 2

                isCell = centerY > cellList[a][2] and centerY < cellList[a][3] and bboxOtherList[3] <= bboxList[3] and itemList[b]["text"].strip().split(" ")[0] == textId

                if itemList[b] is boxList[a] or itemList[b] in removeList or bboxOtherList[2] > bboxList[0] or (left != None and bboxOtherList[0] < left) or (self._rangeCheck(bboxOtherList, bboxList) == False and isCell == False):
                    continue

                rowList.append(itemList[b])

            rowList.sort(key=lambda itemObject: itemObject["bbox"][0])

            for b in range(len(rowList)):
                textRow = rowList[b]["text"].strip()

                tokenRow = textRow.split(" ")[0]

                if tokenRow != textId and (self._rangeCheck(rowList[b]["bbox"], bboxList) == False or len(tokenRow) > self.countUnitMaximum or textId.endswith(tokenRow) == False or self._letterContain(tokenRow) == False):
                    continue

                removeList.append(rowList[b])

                partObject = self._textMarkPart(rowList[b], rowList[b]["text"].find(tokenRow) + len(tokenRow), len(rowList[b]["text"]))

                if partObject != None:
                    partObject["isRowStart"] = True

                    addList.append(partObject)
                elif b + 1 < len(rowList):
                    rowList[b + 1]["isRowStart"] = True

                boxList[a]["isRowBox"] = True

                if tokenRow == textId:
                    tokenList.append(rowList[b])

                break

        resultList = self._restRemove(itemList, removeList) + addList

        for a in range(len(resultList)):
            bboxList = resultList[a]["bbox"]

            count = 0

            for b in range(len(tokenList)):
                if abs(tokenList[b]["bbox"][0] - bboxList[0]) <= height * self.levelMargin:
                    count += 1

            if resultList[a].get("isRowBox") or count < self.countRowMinimum or self._rowIdCheck(self._textClean(resultList[a]["text"])) == False:
                continue

            resultList[a]["isRowBox"] = True

            startObject = None

            for b in range(len(resultList)):
                bboxOtherList = resultList[b]["bbox"]

                if b != a and bboxOtherList[0] >= bboxList[2] and self._rangeCheck(bboxOtherList, bboxList) and (startObject == None or bboxOtherList[0] < startObject["bbox"][0]):
                    startObject = resultList[b]

            if startObject != None:
                startObject["isRowStart"] = True

        return resultList

    def _frameRuleList(self, horizontalList):
        widthMaximum = 0

        for a in range(len(horizontalList)):
            widthMaximum = max(widthMaximum, horizontalList[a][2] - horizontalList[a][0])

        resultList = []

        for a in range(len(horizontalList)):
            if horizontalList[a][2] - horizontalList[a][0] >= widthMaximum * self.levelFrameRule:
                resultList.append(horizontalList[a])

        return sorted(resultList, key=lambda bboxList: bboxList[1])

    def _bandTitleBuild(self, itemList, horizontalList, height):
        frameList = self._frameRuleList(horizontalList)

        titleList = []
        usedList = []

        for a in range(len(frameList) - 1):
            top = frameList[a][3]
            bottom = frameList[a + 1][1]

            bandList = []

            for b in range(len(itemList)):
                centerY = (itemList[b]["bbox"][1] + itemList[b]["bbox"][3]) / 2

                if centerY > top and centerY < bottom:
                    bandList.append(itemList[b])

            if len(bandList) < 2:
                continue

            edgeList = []

            for b in range(len(bandList)):
                if abs(bandList[b]["bbox"][0] - frameList[a][0]) <= height * self.levelCellInside:
                    edgeList.append(bandList[b])

            edgeList.sort(key=lambda itemObject: itemObject["bbox"][1])

            if len(edgeList) == 0 or edgeList[0]["bbox"][3] - edgeList[0]["bbox"][1] < self._heightMedian(bandList) * self.levelBandTitle:
                continue

            memberList = [edgeList[0]]

            for b in range(1, len(edgeList)):
                bboxList = edgeList[b]["bbox"]
                bboxLastList = memberList[len(memberList) - 1]["bbox"]

                heightLast = bboxLastList[3] - bboxLastList[1]

                if abs(bboxList[3] - bboxList[1] - heightLast) > heightLast * self.levelMargin or bboxList[1] - bboxLastList[3] > heightLast * self.levelLineGap:
                    break

                memberList.append(edgeList[b])

            textTitle = ""

            bboxTitleList = list(memberList[0]["bbox"])

            for b in range(len(memberList)):
                textTitle = self._textAppend(textTitle, memberList[b]["text"])

                bboxTitleList = self._bboxExpand(bboxTitleList, memberList[b]["bbox"])

            bodyLeft = None

            isAlone = True

            for b in range(len(bandList)):
                bboxList = bandList[b]["bbox"]

                if bandList[b] in memberList:
                    continue

                if bboxList[0] >= bboxTitleList[2] and (bodyLeft == None or bboxList[0] < bodyLeft):
                    bodyLeft = bboxList[0]

                if bboxList[0] < bboxTitleList[2] and self._rangeCheck(bboxList, bboxTitleList):
                    isAlone = False

            if isAlone == False or bodyLeft == None:
                continue

            titleList.append({"text": self._spaceNormalize(textTitle), "bbox": bboxTitleList, "top": top, "bodyLeft": bodyLeft})

            usedList = usedList + memberList

        return {"itemList": self._restRemove(itemList, usedList), "titleList": titleList}

    def _bandNoteBuild(self, itemList, titleList, horizontalList, height, blockList):
        frameList = self._frameRuleList(horizontalList)

        usedList = []

        for a in range(len(titleList)):
            top = titleList[a]["top"]

            bottom = None

            for b in range(len(frameList)):
                if frameList[b][1] > top + height and (bottom == None or frameList[b][1] < bottom):
                    bottom = frameList[b][1]

            memberList = []

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                centerY = (bboxList[1] + bboxList[3]) / 2

                if centerY > top and (bottom == None or centerY < bottom) and bboxList[2] <= titleList[a]["bodyLeft"] and itemList[b].get("isRowBox") != True and itemList[b].get("isOptionLine") != True:
                    memberList.append(itemList[b])

            memberList.sort(key=lambda itemObject: itemObject["bbox"][1])

            rowList = []

            for b in range(len(memberList)):
                if len(rowList) > 0 and self._lineSameCheck(rowList[len(rowList) - 1][0]["bbox"], memberList[b]["bbox"]):
                    rowList[len(rowList) - 1].append(memberList[b])
                else:
                    rowList.append([memberList[b]])

            paragraphList = []

            for b in range(len(rowList)):
                rowList[b].sort(key=lambda itemObject: itemObject["bbox"][0])

                bboxList = list(rowList[b][0]["bbox"])

                textRow = ""

                for c in range(len(rowList[b])):
                    textRow = self._textAppend(textRow, rowList[b][c]["text"])

                    bboxList = self._bboxExpand(bboxList, rowList[b][c]["bbox"])

                isJoin = len(paragraphList) > 0

                if isJoin:
                    paragraphObject = paragraphList[len(paragraphList) - 1]

                    bboxLastList = paragraphObject["bboxLast"]

                    isOutdent = abs(bboxList[0] - paragraphObject["bboxFirst"][0]) <= height * self.levelMargin and bboxLastList[0] - bboxList[0] > height * self.levelMargin

                    if rowList[b][0].get("style", "") != paragraphObject["style"] or bboxList[1] - bboxLastList[3] > (bboxLastList[3] - bboxLastList[1]) * self.levelLineGap or isOutdent:
                        isJoin = False

                if isJoin == False:
                    paragraphList.append({"text": textRow, "bbox": bboxList, "bboxFirst": bboxList, "bboxLast": bboxList, "style": rowList[b][0].get("style", "")})

                    continue

                paragraphObject["text"] = self._textAppend(paragraphObject["text"], textRow)
                paragraphObject["bbox"] = self._bboxExpand(paragraphObject["bbox"], bboxList)
                paragraphObject["bboxLast"] = bboxList

            for b in range(len(paragraphList)):
                blockList.append({"text": paragraphList[b]["text"], "bbox": paragraphList[b]["bbox"]})

            usedList = usedList + memberList

        return self._restRemove(itemList, usedList)

    def _bandRowOrder(self, entryList):
        entryList.sort(key=lambda entryObject: entryObject["bbox"][1])

        rowList = []

        for a in range(len(entryList)):
            bboxList = entryList[a]["bbox"]

            centerY = (bboxList[1] + bboxList[3]) / 2

            if len(rowList) > 0:
                bboxRowList = rowList[len(rowList) - 1][0]["bbox"]

                centerRowY = (bboxRowList[1] + bboxRowList[3]) / 2

                isTop = abs(bboxList[1] - bboxRowList[1]) <= min(bboxList[3] - bboxList[1], bboxRowList[3] - bboxRowList[1]) * self.levelLineSame

                if (centerY > bboxRowList[1] and centerY < bboxRowList[3] and centerRowY > bboxList[1] and centerRowY < bboxList[3]) or isTop:
                    rowList[len(rowList) - 1].append(entryList[a])

                    continue

            rowList.append([entryList[a]])

        resultList = []

        for a in range(len(rowList)):
            resultList = resultList + sorted(rowList[a], key=lambda entryObject: entryObject["bbox"][0])

        return resultList

    def _bandTableWrite(self, pairList, lineList):
        if len(pairList) == 0:
            return

        if len(lineList) > 0 and lineList[len(lineList) - 1] != "":
            lineList.append("")

        columnList = self._tableColumnList(pairList)

        lineList.append(f"| {' | '.join(columnList)} |")
        lineList.append(f"|{' --- |' * len(columnList)}")

        for a in range(len(pairList)):
            cellList = []

            for b in range(len(columnList)):
                cellList.append(self._cellEscape(self._spaceNormalize(pairList[a].get(columnList[b], ""))))

            lineList.append(f"| {' | '.join(cellList)} |")

        lineList.append("")

        pairList.clear()

    def _bandWrite(self, pairList, restList, titleList, height):
        entryList = []

        for a in range(len(pairList)):
            entryList.append({"pair": pairList[a], "bbox": self._pairBboxFull(pairList[a]), "index": -1, "isNote": False})

        for a in range(len(restList)):
            entryList.append({"line": restList[a], "bbox": restList[a]["bbox"], "index": -1, "isNote": False})

        titleList.sort(key=lambda titleObject: titleObject["top"])

        for a in range(len(entryList)):
            bboxList = entryList[a]["bbox"]

            centerY = (bboxList[1] + bboxList[3]) / 2

            for b in range(len(titleList)):
                if titleList[b]["top"] <= centerY:
                    entryList[a]["index"] = b

            if entryList[a]["index"] < 0 or bboxList[2] > titleList[entryList[a]["index"]]["bodyLeft"] + height * self.levelMargin:
                continue

            if "pair" in entryList[a] and entryList[a]["pair"]["value"] == "" and entryList[a]["pair"]["row"] == "":
                entryList[a] = {"line": {"text": self._spaceNormalize(entryList[a]["pair"]["key"]), "bbox": bboxList}, "bbox": bboxList, "index": entryList[a]["index"], "isNote": False}

            entryList[a]["isNote"] = True

        lineList = []

        for a in range(-1, len(titleList)):
            noteList = []
            bodyList = []

            for b in range(len(entryList)):
                if entryList[b]["index"] != a:
                    continue

                if entryList[b]["isNote"]:
                    noteList.append(entryList[b])
                else:
                    bodyList.append(entryList[b])

            if a >= 0:
                if len(lineList) > 0 and lineList[len(lineList) - 1] != "":
                    lineList.append("")

                lineList = lineList + [f"### {titleList[a]['text']}", ""]

            orderList = self._bandRowOrder(noteList) + self._bandRowOrder(bodyList)

            runList = []

            for b in range(len(orderList)):
                if "pair" in orderList[b]:
                    if len(runList) > 0 and runList[len(runList) - 1]["section"] != orderList[b]["pair"]["section"]:
                        self._bandTableWrite(runList, lineList)

                    if len(runList) == 0 and orderList[b]["pair"]["section"] != "":
                        if len(lineList) > 0 and lineList[len(lineList) - 1] != "":
                            lineList.append("")

                        lineList = lineList + [f"#### {orderList[b]['pair']['section']}", ""]

                    runList.append(orderList[b]["pair"])

                    continue

                self._bandTableWrite(runList, lineList)

                self._restWrite(orderList[b]["line"], lineList)

            self._bandTableWrite(runList, lineList)

        return lineList

    def _lineSameCheck(self, bboxList, bboxOtherList):
        return self._overlap(bboxList[1], bboxList[3], bboxOtherList[1], bboxOtherList[3]) >= min(bboxList[3] - bboxList[1], bboxOtherList[3] - bboxOtherList[1]) * self.levelLineSame

    def _wallSegment(self, bboxList, verticalList):
        centerX = (bboxList[0] + bboxList[2]) / 2

        left = None
        right = None

        for a in range(len(verticalList)):
            bboxLineList = verticalList[a]

            if self._overlap(bboxLineList[1], bboxLineList[3], bboxList[1], bboxList[3]) < (bboxList[3] - bboxList[1]) * self.levelLineCover:
                continue

            center = (bboxLineList[0] + bboxLineList[2]) / 2

            if center <= centerX and (left == None or center > left):
                left = center

            if center > centerX and (right == None or center < right):
                right = center

        return (left, right)

    def _markerText(self, textItem):
        result = self._textClean(textItem)

        while len(result) > 0 and result[0] in self.reference.leaderList:
            result = result[1:]

        while len(result) > 0 and result[len(result) - 1] in self.reference.leaderList:
            result = result[0:len(result) - 1]

        return result

    def _markerCheck(self, textItem):
        count = 0

        for a in range(len(textItem)):
            if unicodedata.category(textItem[a])[0] in ["L", "N"]:
                count += 1
            elif unicodedata.category(textItem[a]) not in ["Ps", "Pe"]:
                return False

        return count > 0 and count <= self.countUnitMaximum

    def _rowIdColumnCheck(self, itemObject, bboxIdList):
        textItem = self._textClean(itemObject["text"])

        if len(textItem) == 0 or len(textItem) > self.countRowId:
            return False

        for a in range(len(textItem)):
            if unicodedata.category(textItem[a])[0] not in ["L", "N"]:
                return False

        count = 0

        for a in range(len(bboxIdList)):
            if self._overlap(bboxIdList[a][0], bboxIdList[a][2], itemObject["bbox"][0], itemObject["bbox"][2]) > 0:
                count += 1

        return count >= self.countRowMinimum

    def _optionKeyAbove(self, keyList, itemList, height, usedList, segment):
        resultList = list(keyList)

        isFound = True

        while isFound:
            isFound = False

            bboxFirstList = resultList[0]["bbox"]

            for a in range(len(itemList)):
                bboxList = itemList[a]["bbox"]

                gap = bboxFirstList[1] - bboxList[3]

                if itemList[a] in usedList or itemList[a] in resultList or itemList[a].get("isRowBox") or itemList[a].get("style", "") != resultList[0].get("style", "") or abs(bboxList[0] - bboxFirstList[0]) > height * self.levelMargin or gap < -height * self.levelLineGap or gap > height * self.levelLineGap:
                    continue

                if (segment[0] != None and bboxList[0] < segment[0]) or (segment[1] != None and bboxList[2] > segment[1]):
                    continue

                resultList.insert(0, itemList[a])

                isFound = True

                break

        return resultList

    def _lineContinueCheck(self, itemObject, itemList, height):
        bboxList = itemObject["bbox"]

        for a in range(len(itemList)):
            bboxOtherList = itemList[a]["bbox"]

            gap = bboxList[1] - bboxOtherList[3]

            if itemList[a] is not itemObject and abs(bboxOtherList[0] - bboxList[0]) <= height * self.levelMargin and gap >= -height * self.levelLineGap and gap <= height * self.levelLineGap:
                return True

        return False

    def _optionConnectCheck(self, right, left, bboxLineList, itemRawList, height):
        rawList = []

        for a in range(len(itemRawList)):
            bboxList = itemRawList[a]["bbox"]

            if self._lineSameCheck(bboxList, bboxLineList) and bboxList[2] > right - height * self.levelMargin and bboxList[0] < left:
                rawList.append(bboxList)

        rawList.sort(key=lambda bboxList: bboxList[0])

        cursor = right

        for a in range(len(rawList)):
            if rawList[a][0] - cursor > height * self.levelKeyGap:
                return False

            cursor = max(cursor, rawList[a][2])

        return left - cursor <= height * self.levelKeyGap

    def _optionKeyCell(self, groupBoxList, memberList, itemList, boxList, lineObject, usedList):
        cell = self._cellFind(groupBoxList[0]["bbox"], lineObject)

        if cell == None:
            return []

        for a in range(len(boxList)):
            bboxList = boxList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            if boxList[a] not in groupBoxList and centerX > cell[0] and centerX < cell[1] and centerY > cell[2] and centerY < cell[3]:
                return []

        resultList = []

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            if itemList[a] in memberList or itemList[a] in usedList or centerX < cell[0] or centerX > cell[1] or centerY < cell[2] or centerY > cell[3]:
                continue

            if centerY > groupBoxList[0]["bbox"][1]:
                return []

            resultList.append(itemList[a])

        return sorted(resultList, key=lambda itemObject: (itemObject["bbox"][1], itemObject["bbox"][0]))

    def _optionLineBuild(self, itemList, circleList, lineObject, height, itemRawList, bboxIdList):
        boxList = []

        for a in range(len(circleList)):
            if circleList[a].get("isBox"):
                boxList.append(circleList[a])

        boxList.sort(key=lambda boxObject: (boxObject["bbox"][1], boxObject["bbox"][0]))

        groupList = []

        for a in range(len(boxList)):
            segment = self._wallSegment(boxList[a]["bbox"], lineObject["verticalList"])

            isAdded = False

            for b in range(len(groupList)):
                if groupList[b]["segment"] == segment and self._lineSameCheck(groupList[b]["boxList"][0]["bbox"], boxList[a]["bbox"]):
                    groupList[b]["boxList"].append(boxList[a])

                    isAdded = True

                    break

            if isAdded == False:
                groupList.append({"segment": segment, "boxList": [boxList[a]]})

        usedList = []
        addList = []
        pairList = []
        boxUsedList = []

        for a in range(len(groupList)):
            segment = groupList[a]["segment"]

            groupBoxList = sorted(groupList[a]["boxList"], key=lambda boxObject: boxObject["bbox"][0])

            bboxLineList = groupBoxList[0]["bbox"]

            size = bboxLineList[2] - bboxLineList[0]

            memberList = []

            isRowBox = False

            rowLeftObject = None

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                if itemList[b].get("isRowBox"):
                    if bboxList[0] > groupBoxList[len(groupBoxList) - 1]["bbox"][2] and self._rangeCheck(bboxList, bboxLineList):
                        isRowBox = True

                    if bboxList[2] <= groupBoxList[0]["bbox"][0] and self._lineSameCheck(bboxList, bboxLineList) and (segment[0] == None or bboxList[0] > segment[0]):
                        rowLeftObject = itemList[b]

                    continue

                if itemList[b] in usedList or self._lineSameCheck(bboxList, bboxLineList) == False:
                    continue

                centerX = (bboxList[0] + bboxList[2]) / 2

                if (segment[0] == None or centerX > segment[0]) and (segment[1] == None or centerX < segment[1]):
                    memberList.append(itemList[b])

            memberList.sort(key=lambda itemObject: itemObject["bbox"][0])

            optionList = []

            for b in range(len(groupBoxList)):
                bboxBoxList = groupBoxList[b]["bbox"]

                markerObject = None

                for c in range(len(memberList)):
                    gap = bboxBoxList[0] - memberList[c]["bbox"][2]

                    if gap < -size * self.levelOptionBoxGap or gap > size * self.levelOptionBoxLabel or (b > 0 and memberList[c]["bbox"][0] - groupBoxList[b - 1]["bbox"][2] <= gap):
                        continue

                    if markerObject == None or memberList[c]["bbox"][2] > markerObject["bbox"][2]:
                        markerObject = memberList[c]

                optionList.append({"box": groupBoxList[b], "marker": markerObject, "labelList": []})

            countMarker = 0

            for b in range(len(optionList)):
                markerObject = optionList[b]["marker"]

                if markerObject != None and self._markerCheck(self._markerText(markerObject["text"])):
                    countMarker += 1
                elif b > 0:
                    optionList[b]["marker"] = None

            keyList = []

            for b in range(len(memberList)):
                if memberList[b]["bbox"][2] <= groupBoxList[0]["bbox"][0] + size * self.levelOptionBoxGap:
                    keyList.append(memberList[b])

            markerFirstObject = optionList[0]["marker"]

            if markerFirstObject != None and self._markerCheck(self._markerText(markerFirstObject["text"])) == False:
                optionList[0]["marker"] = None

                textMarker = markerFirstObject["text"].rstrip()

                indexSpace = textMarker.rfind(" ")

                if countMarker > 0 and indexSpace > 0 and self._markerCheck(self._markerText(textMarker[indexSpace:])):
                    partKeyObject = self._textMarkPart(markerFirstObject, 0, indexSpace)
                    partMarkerObject = self._textMarkPart(markerFirstObject, indexSpace, len(textMarker))

                    if partKeyObject != None and partMarkerObject != None:
                        keyList[keyList.index(markerFirstObject)] = partKeyObject

                        optionList[0]["marker"] = partMarkerObject

                        usedList.append(markerFirstObject)
            elif markerFirstObject != None and markerFirstObject in keyList:
                keyList.remove(markerFirstObject)

            for b in range(len(optionList)):
                bboxBoxList = optionList[b]["box"]["bbox"]

                limit = None

                if b + 1 < len(optionList):
                    limit = optionList[b + 1]["marker"]["bbox"][0] if optionList[b + 1]["marker"] != None else optionList[b + 1]["box"]["bbox"][0]

                for c in range(len(memberList)):
                    if memberList[c]["bbox"][0] >= bboxBoxList[2] - size * self.levelOptionBoxGap and (limit == None or memberList[c]["bbox"][2] <= limit + size * self.levelOptionBoxGap) and (b + 1 == len(optionList) or memberList[c] is not optionList[b + 1]["marker"]):
                        optionList[b]["labelList"].append(memberList[c])

                if len(optionList[b]["labelList"]) > 0 and (optionList[b]["labelList"][0]["bbox"][0] - bboxBoxList[2] > size * self.levelOptionBoxLabel or self._lineContinueCheck(optionList[b]["labelList"][0], itemList, height)):
                    optionList[b]["labelList"] = []

            optionLeft = optionList[0]["marker"]["bbox"][0] if optionList[0]["marker"] != None else groupBoxList[0]["bbox"][0]

            keyConnectList = []

            for b in range(len(keyList) - 1, -1, -1):
                if self._optionConnectCheck(keyList[b]["bbox"][2], optionLeft, bboxLineList, itemRawList, height) == False:
                    break

                keyConnectList.insert(0, keyList[b])

                optionLeft = keyList[b]["bbox"][0]

            keyList = keyConnectList

            rowObject = None

            for b in range(len(keyList) - 1, -1, -1):
                if self._rowIdColumnCheck(keyList[b], bboxIdList):
                    rowObject = keyList[b]

                    keyList = keyList[b + 1:]

                    break

            if rowObject == None and optionList[0]["marker"] != None and self._rowIdColumnCheck(optionList[0]["marker"], bboxIdList):
                rowObject = optionList[0]["marker"]

                optionList[0]["marker"] = None

            if rowObject == None and isRowBox == False:
                rowObject = rowLeftObject

            if len(keyList) == 0 and rowObject == None:
                keyList = self._optionKeyCell(groupBoxList, memberList, itemList, boxList, lineObject, usedList)

            if len(keyList) == 0 and rowObject == None:
                continue

            textOptionList = []

            claimList = []

            if rowObject != None:
                claimList.append(rowObject)

            for b in range(len(optionList)):
                textOption = self.textMark if optionList[b]["box"].get("isMark") else self.textOption

                if optionList[b]["marker"] != None:
                    textOption = f"{self._markerText(optionList[b]['marker']['text'])} {textOption}"

                    claimList.append(optionList[b]["marker"])

                for c in range(len(optionList[b]["labelList"])):
                    textOption = self._textAppend(textOption, optionList[b]["labelList"][c]["text"])

                    claimList.append(optionList[b]["labelList"][c])

                textOptionList.append(textOption)

                boxUsedList.append(optionList[b]["box"])

            textKey = ""

            for b in range(len(keyList)):
                textKey = self._textAppend(textKey, keyList[b]["text"])

            if isRowBox:
                if len(keyList) > 0:
                    keyList = self._optionKeyAbove(keyList, itemList, height, usedList + claimList, segment)

                    textKey = ""

                    for b in range(len(keyList)):
                        textKey = self._textAppend(textKey, keyList[b]["text"])

                mergeObject = dict(keyList[0]) if len(keyList) > 0 else dict(claimList[0])

                mergeObject["text"] = self._textAppend(textKey, " / ".join(textOptionList))
                mergeObject["charList"] = []
                mergeObject["isOptionLine"] = True

                bboxMergeList = list(mergeObject["bbox"])

                mergeList = keyList + claimList

                for b in range(len(mergeList)):
                    bboxMergeList = self._bboxExpand(bboxMergeList, mergeList[b]["bbox"])

                    if mergeList[b].get("isRowStart"):
                        mergeObject["isRowStart"] = True

                for b in range(len(groupBoxList)):
                    bboxMergeList = [min(bboxMergeList[0], groupBoxList[b]["bbox"][0]), bboxMergeList[1], max(bboxMergeList[2], groupBoxList[b]["bbox"][2]), bboxMergeList[3]]

                mergeObject["bbox"] = bboxMergeList

                addList.append(mergeObject)

                usedList = usedList + keyList + claimList

                continue

            if len(keyList) > 0 and self._lineSameCheck(keyList[len(keyList) - 1]["bbox"], bboxLineList):
                keyList = self._optionKeyAbove(keyList, itemList, height, usedList + claimList, segment)

                textKey = ""

                for b in range(len(keyList)):
                    textKey = self._textAppend(textKey, keyList[b]["text"])

            bboxKeyList = list(keyList[0]["bbox"]) if len(keyList) > 0 else list(rowObject["bbox"])

            for b in range(len(keyList)):
                bboxKeyList = self._bboxExpand(bboxKeyList, keyList[b]["bbox"])

            bboxFullList = list(bboxKeyList)

            for b in range(len(claimList)):
                bboxFullList = self._bboxExpand(bboxFullList, claimList[b]["bbox"])

            for b in range(len(groupBoxList)):
                bboxFullList = self._bboxExpand(bboxFullList, groupBoxList[b]["bbox"])

            pairList.append({
                "y": bboxKeyList[1],
                "bbox": bboxKeyList,
                "bboxKey": bboxKeyList,
                "bboxFull": bboxFullList,
                "section": "",
                "group": "",
                "sectionList": [],
                "row": self._textClean(rowObject["text"]) if rowObject != None else "",
                "key": self._spaceNormalize(textKey),
                "formula": "",
                "value": " / ".join(textOptionList),
                "isOptionLine": True,
                "isSelfField": True
            })

            usedList = usedList + keyList + claimList

        circleRestList = []

        for a in range(len(circleList)):
            if circleList[a] not in boxUsedList:
                circleRestList.append(circleList[a])

        return {"itemList": self._restRemove(itemList, usedList) + addList, "circleList": circleRestList, "pairList": pairList}

    def _optionListBuild(self, circleList, itemList, lineObject, height, blockList):
        boxList = []

        for a in range(len(circleList)):
            if circleList[a].get("isBox"):
                boxList.append(circleList[a])

        boxList.sort(key=lambda boxObject: (boxObject["bbox"][1], boxObject["bbox"][0]))

        wallList = []

        for a in range(len(lineObject["verticalList"])):
            bboxList = lineObject["verticalList"][a]

            isEdge = False

            for b in range(len(boxList)):
                bboxBoxList = boxList[b]["bbox"]

                reach = (bboxBoxList[2] - bboxBoxList[0]) * self.levelOptionBoxGap

                if bboxList[0] >= bboxBoxList[0] - reach and bboxList[2] <= bboxBoxList[2] + reach and bboxList[1] >= bboxBoxList[1] - reach and bboxList[3] <= bboxBoxList[3] + reach:
                    isEdge = True

                    break

            if isEdge == False:
                wallList.append(bboxList)

        optionList = []
        usedList = []

        for a in range(len(boxList)):
            bboxBoxList = boxList[a]["bbox"]

            size = bboxBoxList[2] - bboxBoxList[0]

            segment = self._wallSegment(bboxBoxList, wallList)

            cell = self._cellFind(bboxBoxList, {"verticalList": wallList, "horizontalList": lineObject["horizontalList"]})

            isNeighbor = False

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                centerY = (bboxList[1] + bboxList[3]) / 2

                if cell != None and bboxList[2] <= cell[0] + height * self.levelCellInside and centerY > cell[2] and centerY < cell[3]:
                    isNeighbor = True

                    break

            if isNeighbor:
                continue

            limit = None

            for b in range(len(boxList)):
                bboxNextList = boxList[b]["bbox"]

                if b != a and self._lineSameCheck(bboxNextList, bboxBoxList) and bboxNextList[0] > bboxBoxList[2] and (limit == None or bboxNextList[0] < limit):
                    limit = bboxNextList[0]

            rowList = []

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                if itemList[b] in usedList or itemList[b].get("isRowBox") or self._lineSameCheck(bboxList, bboxBoxList) == False or bboxList[0] < bboxBoxList[2] - size * self.levelOptionBoxGap:
                    continue

                if (limit != None and bboxList[2] > limit + size * self.levelOptionBoxGap) or (segment[1] != None and bboxList[0] > segment[1]):
                    continue

                rowList.append(itemList[b])

            rowList.sort(key=lambda itemObject: itemObject["bbox"][0])

            labelList = []

            cursor = bboxBoxList[2]

            reach = size * self.levelOptionBoxLabel

            for b in range(len(rowList)):
                if rowList[b]["bbox"][0] - cursor > reach:
                    break

                labelList.append(rowList[b])

                cursor = max(cursor, rowList[b]["bbox"][2])

                reach = height * self.levelKeyGap

            if len(labelList) == 0:
                continue

            usedList = usedList + labelList

            optionList.append({"box": boxList[a], "labelList": labelList, "segment": segment})

        for a in range(len(optionList)):
            labelList = optionList[a]["labelList"]

            segment = optionList[a]["segment"]

            bboxLineList = labelList[0]["bbox"]

            isFound = True

            while isFound:
                isFound = False

                candidateObject = None

                for b in range(len(itemList)):
                    bboxList = itemList[b]["bbox"]

                    gap = bboxList[1] - bboxLineList[3]

                    if itemList[b] in usedList or itemList[b].get("isRowBox") or abs(bboxList[0] - labelList[0]["bbox"][0]) > height * self.levelMargin or gap < -height * self.levelLineGap or gap > height * self.levelOptionLineGap:
                        continue

                    if (segment[0] != None and bboxList[0] < segment[0]) or (segment[1] != None and bboxList[2] > segment[1]):
                        continue

                    if candidateObject == None or bboxList[1] < candidateObject["bbox"][1]:
                        candidateObject = itemList[b]

                if candidateObject == None:
                    break

                pitch = candidateObject["bbox"][1] - bboxLineList[1]

                isParagraph = False

                for b in range(len(itemList)):
                    bboxList = itemList[b]["bbox"]

                    pitchNext = bboxList[1] - candidateObject["bbox"][1]

                    if itemList[b] not in usedList and abs(bboxList[0] - candidateObject["bbox"][0]) <= height * self.levelMargin and pitchNext > 0 and pitchNext < pitch - height * self.levelMargin:
                        isParagraph = True

                if isParagraph:
                    break

                labelList.append(candidateObject)

                usedList.append(candidateObject)

                bboxLineList = candidateObject["bbox"]

                isFound = True

        groupList = []

        for a in range(len(optionList)):
            optionObject = optionList[a]

            textOption = self.textMark if optionObject["box"].get("isMark") else self.textOption

            bboxList = list(optionObject["box"]["bbox"])

            for b in range(len(optionObject["labelList"])):
                textOption = self._textAppend(textOption, optionObject["labelList"][b]["text"])

                bboxList = self._bboxExpand(bboxList, optionObject["labelList"][b]["bbox"])

            optionObject["text"] = textOption
            optionObject["bbox"] = bboxList

            indexGroup = -1

            for b in range(len(groupList) - 1, -1, -1):
                groupObject = groupList[b]

                if groupObject["segment"] != optionObject["segment"] or bboxList[1] - groupObject["bbox"][3] > height * self.levelFieldGap or self._ruleBetweenCheck(lineObject["horizontalList"], groupObject["bbox"], bboxList):
                    continue

                isCross = False

                for c in range(len(groupObject["optionList"])):
                    bboxOtherList = groupObject["optionList"][c]["bbox"]

                    if abs(bboxOtherList[0] - bboxList[0]) > height * self.levelMargin and self._lineSameCheck(groupObject["optionList"][c]["box"]["bbox"], optionObject["box"]["bbox"]) == False and self._overlap(bboxOtherList[0], bboxOtherList[2], bboxList[0], bboxList[2]) > 0:
                        isCross = True

                if isCross == False:
                    indexGroup = b

                    break

            if indexGroup < 0:
                groupList.append({"segment": optionObject["segment"], "bbox": list(bboxList), "optionList": []})

                indexGroup = len(groupList) - 1

            groupList[indexGroup]["optionList"].append(optionObject)
            groupList[indexGroup]["bbox"] = self._bboxExpand(groupList[indexGroup]["bbox"], bboxList)

        boxUsedList = []

        for a in range(len(groupList)):
            memberList = groupList[a]["optionList"]

            isRow = True

            for b in range(len(memberList)):
                boxUsedList.append(memberList[b]["box"])

                if self._lineSameCheck(memberList[0]["box"]["bbox"], memberList[b]["box"]["bbox"]) == False:
                    isRow = False

            memberList.sort(key=lambda optionObject: optionObject["bbox"][0])

            if isRow:
                blockList.append({"bbox": groupList[a]["bbox"], "text": " / ".join([optionObject["text"] for optionObject in memberList])})

                continue

            columnList = []

            for b in range(len(memberList)):
                if len(columnList) > 0 and memberList[b]["bbox"][0] - columnList[len(columnList) - 1][0]["bbox"][0] <= height * self.levelMargin:
                    columnList[len(columnList) - 1].append(memberList[b])
                else:
                    columnList.append([memberList[b]])

            lineList = []

            for b in range(len(columnList)):
                columnList[b].sort(key=lambda optionObject: optionObject["bbox"][1])

                for c in range(len(columnList[b])):
                    lineList.append(f"- {columnList[b][c]['text']}")

            blockList.append({"bbox": groupList[a]["bbox"], "text": "", "lineList": lineList})

        return {"itemList": self._restRemove(itemList, usedList), "circleList": self._restRemove(circleList, boxUsedList)}

    def _rowIdComplete(self, pairList):
        entryList = []

        for a in range(len(pairList)):
            entryList.append({"pair": pairList[a], "bbox": self._pairBboxFull(pairList[a])})

        entryList = self._bandRowOrder(entryList)

        orderList = []

        for a in range(len(entryList)):
            orderList.append(entryList[a]["pair"])

        number = ""

        for a in range(len(orderList)):
            key = orderList[a]["key"]

            rowLast = orderList[a - 1]["row"] if a > 0 else ""

            if orderList[a]["row"] == "" and rowLast != "" and len(key) > 2 and unicodedata.category(key[1]) == "Zs" and unicodedata.category(key[0])[0] == "L" and unicodedata.category(rowLast[len(rowLast) - 1]) == unicodedata.category(key[0]) and ord(key[0]) == ord(rowLast[len(rowLast) - 1]) + 1:
                orderList[a]["row"] = key[0]
                orderList[a]["key"] = key[2:].strip()

            row = orderList[a]["row"]

            index = 0

            while index < len(row) and unicodedata.category(row[index]) == "Nd":
                index += 1

            if index > 0:
                number = row[0:index]
            elif row != "" and number != "" and self._letterOnlyCheck(row):
                orderList[a]["row"] = f"{number}{row}"

    def _matrixLineText(self, itemList):
        rowList = []

        orderList = sorted(itemList, key=lambda itemObject: itemObject["bbox"][1])

        for a in range(len(orderList)):
            isAdded = False

            for b in range(len(rowList)):
                if self._lineSameCheck(rowList[b][0]["bbox"], orderList[a]["bbox"]):
                    rowList[b].append(orderList[a])

                    isAdded = True

                    break

            if isAdded == False:
                rowList.append([orderList[a]])

        result = ""

        for a in range(len(rowList)):
            memberList = sorted(rowList[a], key=lambda itemObject: itemObject["bbox"][0])

            for b in range(len(memberList)):
                result = self._textAppend(result, memberList[b]["text"])

        return result

    def _matrixCellText(self, boxList, itemList, height):
        boxList = sorted(boxList, key=lambda boxObject: (boxObject["bbox"][1], boxObject["bbox"][0]))

        optionList = []
        usedList = []

        for a in range(len(boxList)):
            bboxBoxList = boxList[a]["bbox"]

            size = bboxBoxList[2] - bboxBoxList[0]

            markerObject = None

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                gap = bboxBoxList[0] - bboxList[2]

                if self._lineSameCheck(bboxList, bboxBoxList) == False or gap < -size * self.levelOptionBoxGap or gap > size * self.levelOptionBoxLabel or self._markerCheck(self._markerText(itemList[b]["text"])) == False:
                    continue

                if markerObject == None or bboxList[2] > markerObject["bbox"][2]:
                    markerObject = itemList[b]

            if markerObject != None:
                usedList.append(markerObject)

            optionList.append({"box": boxList[a], "marker": markerObject, "labelList": []})

        for a in range(len(optionList)):
            bboxBoxList = optionList[a]["box"]["bbox"]

            size = bboxBoxList[2] - bboxBoxList[0]

            limit = None

            for b in range(len(optionList)):
                bboxNextList = optionList[b]["marker"]["bbox"] if optionList[b]["marker"] != None else optionList[b]["box"]["bbox"]

                if b != a and self._lineSameCheck(bboxNextList, bboxBoxList) and bboxNextList[0] > bboxBoxList[2] and (limit == None or bboxNextList[0] < limit):
                    limit = bboxNextList[0]

            labelList = []

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                if itemList[b] not in usedList and self._lineSameCheck(bboxList, bboxBoxList) and bboxList[0] >= bboxBoxList[2] - size * self.levelOptionBoxGap and (limit == None or bboxList[2] <= limit + size * self.levelOptionBoxGap):
                    labelList.append(itemList[b])

            labelList.sort(key=lambda itemObject: itemObject["bbox"][0])

            if len(labelList) == 0 or labelList[0]["bbox"][0] - bboxBoxList[2] > size * self.levelOptionBoxLabel:
                continue

            optionList[a]["labelList"] = labelList

            usedList = usedList + labelList

        for a in range(len(optionList)):
            labelList = optionList[a]["labelList"]

            isFound = len(labelList) > 0

            while isFound:
                isFound = False

                bboxLastList = labelList[len(labelList) - 1]["bbox"]

                for b in range(len(itemList)):
                    bboxList = itemList[b]["bbox"]

                    gap = bboxList[1] - bboxLastList[3]

                    if itemList[b] in usedList or abs(bboxList[0] - labelList[0]["bbox"][0]) > height * self.levelMargin or gap < -height * self.levelLineGap or gap > height * self.levelLineGap:
                        continue

                    labelList.append(itemList[b])

                    usedList.append(itemList[b])

                    isFound = True

                    break

        textOptionList = []

        for a in range(len(optionList)):
            textOption = self.textMark if optionList[a]["box"].get("isMark") else self.textOption

            if optionList[a]["marker"] != None:
                textOption = f"{self._markerText(optionList[a]['marker']['text'])} {textOption}"

            for b in range(len(optionList[a]["labelList"])):
                textOption = self._textAppend(textOption, optionList[a]["labelList"][b]["text"])

            textOptionList.append(textOption)

        return self._textAppend(self._matrixLineText(self._restRemove(itemList, usedList)), " / ".join(textOptionList))

    def _matrixEdgeList(self, positionList, margin):
        resultList = []

        positionList = sorted(positionList)

        for a in range(len(positionList)):
            if len(resultList) == 0 or positionList[a] - resultList[len(resultList) - 1] > margin:
                resultList.append(positionList[a])

        return resultList

    def _matrixIndex(self, edgeList, position):
        for a in range(len(edgeList) - 1):
            if position > edgeList[a] and position <= edgeList[a + 1]:
                return a

        return -1

    def _matrixBuild(self, itemList, circleList, lineObject, height, matrixList):
        margin = height * self.levelCellInside

        groupList = []

        for a in range(len(lineObject["verticalList"])):
            bboxList = lineObject["verticalList"][a]

            isAdded = False

            for b in range(len(groupList)):
                if abs(groupList[b][0][1] - bboxList[1]) <= margin and abs(groupList[b][0][3] - bboxList[3]) <= margin:
                    groupList[b].append(bboxList)

                    isAdded = True

                    break

            if isAdded == False:
                groupList.append([bboxList])

        groupList.sort(key=lambda wallList: wallList[0][1] - wallList[0][3])

        itemUsedList = []
        boxUsedList = []

        for a in range(len(groupList)):
            top = groupList[a][0][1]
            bottom = groupList[a][0][3]

            columnEdgeList = self._matrixEdgeList([(bboxList[0] + bboxList[2]) / 2 for bboxList in groupList[a]], margin)

            ruleList = []

            for b in range(len(lineObject["horizontalList"])):
                bboxList = lineObject["horizontalList"][b]

                centerY = (bboxList[1] + bboxList[3]) / 2

                if bboxList[0] <= columnEdgeList[0] + margin and bboxList[2] >= columnEdgeList[len(columnEdgeList) - 1] - margin and centerY >= top - margin and centerY <= bottom + margin:
                    ruleList.append(bboxList)

            if len(columnEdgeList) < 2 or len(ruleList) < 2:
                continue

            leftList = sorted([bboxList[0] for bboxList in ruleList])
            rightList = sorted([bboxList[2] for bboxList in ruleList])

            columnEdgeList = self._matrixEdgeList(columnEdgeList + [leftList[int(len(leftList) / 2)], rightList[int(len(rightList) / 2)]], margin)

            rowEdgeList = self._matrixEdgeList([(bboxList[1] + bboxList[3]) / 2 for bboxList in ruleList] + [top, bottom], margin)

            countRow = len(rowEdgeList) - 1
            countColumn = len(columnEdgeList) - 1

            bboxGridList = [columnEdgeList[0], rowEdgeList[0], columnEdgeList[countColumn], rowEdgeList[countRow]]

            isValid = countRow >= self.countMatrixMinimum and countColumn >= self.countMatrixMinimum

            for b in range(len(matrixList)):
                if self._overlap(matrixList[b]["bbox"][0], matrixList[b]["bbox"][2], bboxGridList[0], bboxGridList[2]) > 0 and self._overlap(matrixList[b]["bbox"][1], matrixList[b]["bbox"][3], bboxGridList[1], bboxGridList[3]) > 0:
                    isValid = False

            if isValid == False:
                continue

            cellItemList = [[[] for c in range(countColumn)] for b in range(countRow)]
            cellBoxList = [[[] for c in range(countColumn)] for b in range(countRow)]

            memberList = []
            boxMemberList = []

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                indexRow = self._matrixIndex(rowEdgeList, (bboxList[1] + bboxList[3]) / 2)
                indexColumn = self._matrixIndex(columnEdgeList, (bboxList[0] + bboxList[2]) / 2)

                if indexRow < 0 or indexColumn < 0:
                    continue

                if bboxList[0] < columnEdgeList[indexColumn] - margin or bboxList[2] > columnEdgeList[indexColumn + 1] + margin:
                    isValid = False

                    break

                cellItemList[indexRow][indexColumn].append(itemList[b])

                memberList.append(itemList[b])

            for b in range(len(circleList)):
                bboxList = circleList[b]["bbox"]

                indexRow = self._matrixIndex(rowEdgeList, (bboxList[1] + bboxList[3]) / 2)
                indexColumn = self._matrixIndex(columnEdgeList, (bboxList[0] + bboxList[2]) / 2)

                if indexRow < 0 or indexColumn < 0:
                    continue

                if circleList[b].get("isBox") != True or indexRow == 0 or indexColumn == 0:
                    isValid = False

                    break

                cellBoxList[indexRow][indexColumn].append(circleList[b])

                boxMemberList.append(circleList[b])

            if isValid == False or len(cellItemList[0][0]) > 0:
                continue

            for b in range(1, countRow):
                if len(cellItemList[b][0]) == 0:
                    isValid = False

            for b in range(1, countColumn):
                if len(cellItemList[0][b]) == 0:
                    isValid = False

            if isValid == False:
                continue

            lineList = []

            for b in range(countRow):
                cellList = []

                for c in range(countColumn):
                    cellList.append(self._cellEscape(self._matrixCellText(cellBoxList[b][c], cellItemList[b][c], height)))

                if b == 0:
                    cellList[0] = "key"

                lineList.append(f"| {' | '.join(cellList)} |")

                if b == 0:
                    lineList.append(f"|{' --- |' * countColumn}")

            matrixList.append({"bbox": bboxGridList, "lineList": lineList})

            itemUsedList = itemUsedList + memberList
            boxUsedList = boxUsedList + boxMemberList

        return {"itemList": self._restRemove(itemList, itemUsedList), "circleList": self._restRemove(circleList, boxUsedList)}

    def _fieldLabelExtend(self, labelObject, itemList, usedList, height, fieldList):
        resultList = [labelObject]

        isFound = True

        while isFound:
            isFound = False

            for a in range(len(itemList)):
                bboxList = itemList[a]["bbox"]

                if itemList[a] in resultList or itemList[a] in usedList or itemList[a].get("fieldIndex", 0) != 0 or itemList[a].get("isRowBox") or abs(bboxList[0] - labelObject["bbox"][0]) > height * self.levelMargin:
                    continue

                isField = False

                for b in range(len(fieldList)):
                    if fieldList[b]["bbox"][0] >= bboxList[2] - height * self.levelMargin and self._lineSameCheck(fieldList[b]["bbox"], bboxList) and self._lineSameCheck(fieldList[b]["bbox"], labelObject["bbox"]) == False:
                        isField = True

                for b in range(len(itemList)):
                    gap = bboxList[0] - itemList[b]["bbox"][2]

                    if itemList[b] is not itemList[a] and gap >= 0 and gap <= height * self.levelKeyGap and self._lineSameCheck(itemList[b]["bbox"], bboxList) and self._lineSameCheck(itemList[b]["bbox"], labelObject["bbox"]) == False and self._rowIdCheck(self._textClean(itemList[b]["text"])):
                        isField = True

                if isField:
                    continue

                for b in range(len(resultList)):
                    gapAbove = resultList[b]["bbox"][1] - bboxList[3]
                    gapBelow = bboxList[1] - resultList[b]["bbox"][3]

                    if (gapAbove >= -height * self.levelLineGap and gapAbove <= height * self.levelOptionLineGap) or (gapBelow >= -height * self.levelLineGap and gapBelow <= height * self.levelOptionLineGap):
                        isFound = True

                        break

                if isFound:
                    resultList.append(itemList[a])

                    break

        return resultList

    def _fieldMarkRemove(self, itemList, circleList):
        resultList = []

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            centerX = (bboxList[0] + bboxList[2]) / 2
            centerY = (bboxList[1] + bboxList[3]) / 2

            isBox = False

            for b in range(len(circleList)):
                bboxBoxList = circleList[b]["bbox"]

                if itemList[a].get("fieldIndex", 0) != 0 and circleList[b].get("isBox") and centerX > bboxBoxList[0] and centerX < bboxBoxList[2] and centerY > bboxBoxList[1] and centerY < bboxBoxList[3]:
                    isBox = True

                    break

            if isBox == False:
                resultList.append(itemList[a])

        return resultList

    def _fieldOverlayApply(self, itemList):
        resultList = []

        removeList = []

        for a in range(len(itemList)):
            itemObject = itemList[a]

            if itemObject.get("fieldIndex", 0) != 0:
                resultList.append(itemObject)

                continue

            charList = self._charPosition(itemObject)

            textItem = itemObject["text"]

            if len(charList) != len(textItem):
                charList = self._charPosition({"text": textItem, "bbox": itemObject["bbox"]})

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                if itemList[b].get("fieldIndex", 0) == 0 or len(charList) != len(textItem) or self._lineSameCheck(bboxList, itemObject["bbox"]) == False or self._overlap(bboxList[0], bboxList[2], itemObject["bbox"][0], itemObject["bbox"][2]) <= 0:
                    continue

                indexList = []

                for c in range(len(charList)):
                    center = (charList[c]["start"] + charList[c]["end"]) / 2

                    if center >= bboxList[0] and center <= bboxList[2] and charList[c]["end"] > charList[c]["start"]:
                        indexList.append(c)

                if len(indexList) == 0:
                    continue

                textValue = "" if itemList[b] in removeList else itemList[b]["text"].strip()

                textItem = self._textAppend(self._textAppend(textItem[0:indexList[0]].rstrip(), textValue), textItem[indexList[len(indexList) - 1] + 1:])

                charList = []

                removeList.append(itemList[b])

            if textItem != itemObject["text"]:
                itemObject = dict(itemObject)

                itemObject["text"] = textItem
                itemObject["charList"] = []

            resultList.append(itemObject)

        return self._restRemove(resultList, removeList)

    def _fieldPairBuild(self, itemList, lineObject, height, pairList):
        margin = height * self.levelCellInside

        groupObject = {}

        for a in range(len(itemList)):
            index = itemList[a].get("fieldIndex", 0)

            if index == 0:
                continue

            if index not in groupObject:
                groupObject[index] = []

            groupObject[index].append(itemList[a])

        fieldList = []

        for index in groupObject:
            memberList = groupObject[index]

            bboxList = list(memberList[0]["bbox"])

            isComb = len(memberList) > 1

            for a in range(len(memberList)):
                bboxList = self._bboxExpand(bboxList, memberList[a]["bbox"])

                if len(self._textClean(memberList[a]["text"])) != 1:
                    isComb = False

            fieldList.append({"text": "".join([self._textClean(itemObject["text"]) for itemObject in sorted(memberList, key=lambda itemObject: itemObject["bbox"][0])]) if isComb else self._matrixLineText(memberList), "bbox": bboxList, "itemList": memberList, "isComb": isComb})

        usedList = []

        for a in range(len(fieldList)):
            bboxList = fieldList[a]["bbox"]

            wallList = []
            ruleList = []

            for b in range(len(lineObject["verticalList"])):
                bboxLineList = lineObject["verticalList"][b]

                if fieldList[a]["isComb"] == False or bboxLineList[2] < bboxList[0] - margin or bboxLineList[0] > bboxList[2] + margin or self._overlap(bboxLineList[1], bboxLineList[3], bboxList[1], bboxList[3]) <= 0:
                    wallList.append(bboxLineList)

            for b in range(len(lineObject["horizontalList"])):
                bboxLineList = lineObject["horizontalList"][b]

                if fieldList[a]["isComb"] == False or bboxLineList[0] < bboxList[0] - margin * 2 or bboxLineList[2] > bboxList[2] + margin * 2:
                    ruleList.append(bboxLineList)

            limit = None

            for b in range(len(fieldList)):
                bboxOtherList = fieldList[b]["bbox"]

                if b != a and bboxOtherList[2] <= bboxList[0] and self._overlap(bboxOtherList[1], bboxOtherList[3], bboxList[1], bboxList[3]) > 0 and (limit == None or bboxOtherList[2] > limit):
                    limit = bboxOtherList[2]

            for b in range(len(lineObject["verticalList"])):
                bboxLineList = lineObject["verticalList"][b]

                if bboxLineList[2] <= bboxList[0] - margin and self._overlap(bboxLineList[1], bboxLineList[3], bboxList[1], bboxList[3]) > 0 and (limit == None or bboxLineList[2] > limit):
                    limit = bboxLineList[2]

            labelList = []

            labelObject = None

            for b in range(len(itemList)):
                bboxItemList = itemList[b]["bbox"]

                if itemList[b].get("fieldIndex", 0) != 0 or itemList[b] in usedList or bboxItemList[2] > bboxList[0] + margin or (limit != None and bboxItemList[0] < limit - margin) or self._overlap(bboxItemList[1], bboxItemList[3], bboxList[1], bboxList[3]) <= 0 or bboxList[0] - bboxItemList[2] > height * self.levelLineJoin:
                    continue

                if labelObject == None or bboxItemList[2] > labelObject["bbox"][2]:
                    labelObject = itemList[b]

            rowObject = None

            if labelObject != None:
                labelList = self._fieldLabelExtend(labelObject, itemList, usedList, height, fieldList)

                for b in range(len(itemList)):
                    bboxItemList = itemList[b]["bbox"]

                    gap = labelObject["bbox"][0] - bboxItemList[2]

                    if itemList[b] not in labelList and itemList[b] not in usedList and itemList[b].get("fieldIndex", 0) == 0 and self._lineSameCheck(bboxItemList, labelObject["bbox"]) and gap >= 0 and gap <= height * self.levelKeyGap and self._markerCheck(self._textClean(itemList[b]["text"])):
                        rowObject = itemList[b]

            cell = self._cellFind(bboxList, {"verticalList": wallList, "horizontalList": ruleList})

            isAlone = cell != None and labelObject == None

            for b in range(len(fieldList)):
                bboxOtherList = fieldList[b]["bbox"]

                centerX = (bboxOtherList[0] + bboxOtherList[2]) / 2
                centerY = (bboxOtherList[1] + bboxOtherList[3]) / 2

                if b != a and cell != None and centerX > cell[0] and centerX < cell[1] and centerY > cell[2] and centerY < cell[3]:
                    isAlone = False

            if isAlone:
                for b in range(len(itemList)):
                    bboxItemList = itemList[b]["bbox"]

                    centerX = (bboxItemList[0] + bboxItemList[2]) / 2
                    centerY = (bboxItemList[1] + bboxItemList[3]) / 2

                    if itemList[b].get("fieldIndex", 0) == 0 and itemList[b] not in usedList and centerX > cell[0] and centerX < cell[1] and centerY > cell[2] and centerY < cell[3]:
                        labelList.append(itemList[b])

            if isAlone == False and labelObject == None:
                for b in range(len(itemList)):
                    bboxItemList = itemList[b]["bbox"]

                    gap = bboxList[1] - bboxItemList[3]

                    if itemList[b].get("fieldIndex", 0) != 0 or itemList[b] in usedList or self._overlap(bboxItemList[0], bboxItemList[2], bboxList[0], bboxList[2]) <= 0 or gap < -margin or gap > height * self.levelFieldGap or self._ruleBetweenCheck(lineObject["horizontalList"], bboxItemList, bboxList):
                        continue

                    if labelObject == None or bboxItemList[3] > labelObject["bbox"][3]:
                        labelObject = itemList[b]

                if labelObject != None:
                    labelList = self._fieldLabelExtend(labelObject, itemList, usedList, height, fieldList)

            isLabel = len(labelList) > 0

            for b in range(len(labelList)):
                if labelList[b].get("isRowBox") or self._rowIdCheck(self._textClean(labelList[b]["text"])) or labelList[b].get("isOptionLine"):
                    isLabel = False

            if isLabel == False:
                continue

            bboxKeyList = list(labelList[0]["bbox"])

            for b in range(len(labelList)):
                bboxKeyList = self._bboxExpand(bboxKeyList, labelList[b]["bbox"])

            pairList.append({"y": bboxKeyList[1], "bbox": bboxKeyList, "bboxKey": bboxKeyList, "bboxFull": self._bboxExpand(bboxKeyList, bboxList), "section": "", "group": "", "sectionList": [], "row": self._textClean(rowObject["text"]) if rowObject != None else "", "key": self._spaceNormalize(self._matrixLineText(labelList)), "formula": "", "value": fieldList[a]["text"], "isSelfField": True})

            usedList = usedList + labelList + fieldList[a]["itemList"]

            if rowObject != None:
                usedList.append(rowObject)

        return self._restRemove(itemList, usedList)

    def _restWrite(self, restObject, lineList):
        if "lineList" not in restObject:
            lineList.append(f"- {restObject['text']}")

            return

        if len(lineList) > 0 and lineList[len(lineList) - 1] != "":
            lineList.append("")

        for a in range(len(restObject["lineList"])):
            lineList.append(restObject["lineList"][a])

        lineList.append("")

    def _wallOpenAppend(self, verticalList, position, top, bottom, itemList, margin):
        crossList = []

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            if bboxList[0] < position - 1 and bboxList[2] > position + 1 and bboxList[3] > top and bboxList[1] < bottom:
                crossList.append(bboxList)

        for a in range(len(verticalList)):
            bboxList = verticalList[a]

            if abs((bboxList[0] + bboxList[2]) / 2 - position) <= margin and bboxList[3] > top and bboxList[1] < bottom:
                crossList.append(bboxList)

        crossList.sort(key=lambda bboxList: bboxList[1])

        for a in range(len(crossList)):
            if crossList[a][1] > top:
                verticalList.append([position - 1, top, position + 1, crossList[a][1]])

            top = max(top, crossList[a][3])

        if bottom > top:
            verticalList.append([position - 1, top, position + 1, bottom])

    def _wallNearCheck(self, verticalList, position, margin):
        for a in range(len(verticalList)):
            if abs((verticalList[a][0] + verticalList[a][2]) / 2 - position) <= margin:
                return True

        return False

    def _wallOpenBuild(self, lineObject, height, itemList):
        resultObject = dict(lineObject)

        resultObject["verticalList"] = list(lineObject["verticalList"])
        resultObject["horizontalList"] = list(lineObject["horizontalList"])

        frameList = self._frameRuleList(lineObject["horizontalList"])

        if len(frameList) < 2:
            return resultObject

        margin = height * self.levelCellInside

        edgeList = []

        for a in range(2):
            index = a * 2

            positionList = []

            for b in range(len(frameList)):
                positionList.append(frameList[b][index])

            positionList.sort()

            edgeList.append(positionList[int(len(positionList) / 2)])

        for a in range(2):
            isWall = False

            for b in range(len(lineObject["verticalList"])):
                bboxList = lineObject["verticalList"][b]

                if abs((bboxList[0] + bboxList[2]) / 2 - edgeList[a]) > margin:
                    continue

                for c in range(len(frameList) - 1):
                    if self._overlap(bboxList[1], bboxList[3], frameList[c][3], frameList[c + 1][1]) >= (frameList[c + 1][1] - frameList[c][3]) * self.levelLineCover:
                        isWall = True

                        break

            if isWall == False:
                self._wallOpenAppend(resultObject["verticalList"], edgeList[a], frameList[0][1], frameList[len(frameList) - 1][3], itemList, margin)

        for a in range(2):
            index = a * 2

            ruleList = []

            for b in range(len(lineObject["horizontalList"])):
                bboxList = lineObject["horizontalList"][b]

                if abs(bboxList[2 - index] - edgeList[1 - a]) <= margin and abs(bboxList[index] - edgeList[a]) > margin:
                    ruleList.append(bboxList)

            ruleList.sort(key=lambda bboxList: bboxList[index])

            groupList = []

            for b in range(len(ruleList)):
                if len(groupList) > 0 and ruleList[b][index] - groupList[len(groupList) - 1][0][index] <= margin:
                    groupList[len(groupList) - 1].append(ruleList[b])
                else:
                    groupList.append([ruleList[b]])

            for b in range(len(groupList)):
                position = groupList[b][0][index]

                if len(groupList[b]) < 2 or self._wallNearCheck(lineObject["verticalList"], position, margin):
                    continue

                top = groupList[b][0][1]
                bottom = groupList[b][0][3]

                for c in range(len(groupList[b])):
                    top = min(top, groupList[b][c][1])
                    bottom = max(bottom, groupList[b][c][3])

                topFrame = frameList[0][1]
                bottomFrame = frameList[len(frameList) - 1][3]

                for c in range(len(frameList)):
                    if frameList[c][1] <= top:
                        topFrame = max(topFrame, frameList[c][1])

                    if frameList[c][3] >= bottom:
                        bottomFrame = min(bottomFrame, frameList[c][3])

                self._wallOpenAppend(resultObject["verticalList"], position, topFrame, bottomFrame, itemList, margin)

        wallList = sorted(lineObject["verticalList"], key=lambda bboxList: bboxList[1])

        groupList = []

        for a in range(len(wallList)):
            if len(groupList) > 0 and wallList[a][1] - groupList[len(groupList) - 1][0][1] <= margin:
                groupList[len(groupList) - 1].append(wallList[a])
            else:
                groupList.append([wallList[a]])

        for a in range(len(groupList)):
            position = groupList[a][0][1]

            left = groupList[a][0][0]
            right = groupList[a][0][2]

            for b in range(len(groupList[a])):
                left = min(left, groupList[a][b][0])
                right = max(right, groupList[a][b][2])

            isRule = len(groupList[a]) < 2

            for b in range(len(lineObject["horizontalList"])):
                bboxList = lineObject["horizontalList"][b]

                if abs((bboxList[1] + bboxList[3]) / 2 - position) <= margin and bboxList[0] <= right and bboxList[2] >= left:
                    isRule = True

                    break

            if isRule:
                continue

            leftOpen = left
            rightOpen = right

            for b in range(len(resultObject["verticalList"])):
                bboxList = resultObject["verticalList"][b]

                if bboxList[1] > position or bboxList[3] < position:
                    continue

                if bboxList[2] < left and (leftOpen == left or bboxList[2] > leftOpen):
                    leftOpen = bboxList[2]

                if bboxList[0] > right and (rightOpen == right or bboxList[0] < rightOpen):
                    rightOpen = bboxList[0]

            isCross = False

            for b in range(len(itemList)):
                bboxList = itemList[b]["bbox"]

                if bboxList[1] < position - 1 and bboxList[3] > position + 1 and bboxList[2] > leftOpen and bboxList[0] < rightOpen:
                    isCross = True

                    break

            if isCross == False:
                resultObject["horizontalList"].append([leftOpen, position - 1, rightOpen, position + 1])

        return resultObject

    def execute(self, itemPageList, ringList, lineObject, circleList, numberPage):
        lineObject = self._wallOpenBuild(lineObject, self._heightMedian(itemPageList), itemPageList)

        bandObject = self._bandTitleBuild(itemPageList, lineObject["horizontalList"], self._heightMedian(itemPageList))

        bandTitleList = bandObject["titleList"]

        itemRawList = bandObject["itemList"]

        itemPageList = self._leaderStrip(bandObject["itemList"])

        itemPageList = self._textMarkApply(itemPageList, self._heightMedian(itemPageList), lineObject)

        bboxIdList = []

        for a in range(len(itemPageList)):
            if itemPageList[a].get("fieldIndex", 0) == 0 and self._rowIdCheck(self._textClean(itemPageList[a]["text"])):
                bboxIdList.append(itemPageList[a]["bbox"])

        matrixList = []

        itemPageList = self._fieldOverlayApply(self._fieldMarkRemove(itemPageList, circleList))

        matrixObject = self._matrixBuild(itemPageList, circleList, lineObject, self._heightMedian(itemPageList), matrixList)

        fieldPairList = []

        itemPageList = self._fieldPairBuild(matrixObject["itemList"], lineObject, self._heightMedian(itemPageList), fieldPairList)

        circleList = matrixObject["circleList"]

        itemPageList = self._rowBoxMark(itemPageList, self._heightMedian(itemPageList), lineObject)

        optionObject = self._optionLineBuild(itemPageList, circleList, lineObject, self._heightMedian(itemPageList), itemRawList, bboxIdList)

        optionListObject = self._optionListBuild(optionObject["circleList"], optionObject["itemList"], lineObject, self._heightMedian(itemPageList), matrixList)

        itemPageList = self._bandNoteBuild(optionListObject["itemList"], bandTitleList, lineObject["horizontalList"], self._heightMedian(itemPageList), matrixList)

        circleList = optionListObject["circleList"]

        strikeObject = self._strikeApply(itemPageList, lineObject)

        itemPageList = strikeObject["itemList"]
        lineObject = strikeObject["lineObject"]

        lineObject["blockList"] = matrixList + [{"bbox": pairObject["bboxFull"]} for pairObject in fieldPairList]

        itemPageList = self._itemWallSplit(self._ringArtifactRemove(itemPageList, ringList), lineObject["verticalList"])

        self._enclosedMark(itemPageList, ringList)

        itemPageList = self._overlayJoin(itemPageList)

        itemPageList = self._gapInsert(itemPageList)

        self._markApply(itemPageList, ringList)

        self._optionApply(itemPageList, circleList)

        self._optionBoxApply(itemPageList, circleList)

        verticalBoxList = []

        itemPageList = self._stackTitleCollect(itemPageList, lineObject, verticalBoxList)

        itemPageList = self._stackSparseCollect(itemPageList, lineObject, verticalBoxList)

        itemPageList = self._verticalBoxCollect(itemPageList, verticalBoxList)

        mergeObject = self._verticalMerge(itemPageList, lineObject)

        mergeObject["itemList"] = self._arcFit(mergeObject["itemList"], self._heightMedian(mergeObject["itemList"]), lineObject["horizontalList"])

        mergeObject["itemList"] = self._cellMerge(mergeObject["itemList"], lineObject, self._heightMedian(mergeObject["itemList"]))

        mergeObject["verticalList"] = mergeObject["verticalList"] + verticalBoxList

        heightPage = self._heightMedian(mergeObject["itemList"])

        mergeObject["itemList"] = self._letterMerge(mergeObject["itemList"], heightPage)


        self._optionApply(mergeObject["itemList"], circleList)

        self._optionBoxApply(mergeObject["itemList"], circleList)


        mergeObject["verticalList"] = self._titleStack(self._titleJoin(mergeObject["verticalList"], heightPage), heightPage, lineObject)

        itemList = []

        for a in range(len(mergeObject["itemList"])):
            itemList.append(dict(mergeObject["itemList"][a]))

        itemList.sort(key=lambda itemObject: (itemObject["bbox"][1], itemObject["bbox"][0]))

        height = self._heightMedian(itemList)

        itemList = self._formulaSplit(self._bracketJoin(self._enclosureRemove(itemList), lineObject["verticalList"], height), lineObject["horizontalList"])

        self._typeAssign(itemList, height)

        self._outsideMark(lineObject, itemList)

        self._formulaContinue(itemList, height, lineObject)

        itemList = self._valueCompose(itemList, height, lineObject["horizontalList"], lineObject["verticalList"])

        self._templateZeroMark(itemList)

        self._rowDetect(itemList, height)

        for a in range(len(itemList)):
            if itemList[a].get("isRowBox"):
                itemList[a]["type"] = "row"
                itemList[a]["text"] = self._textClean(itemList[a]["text"])

        self._valueFilter(itemList)

        self._referenceAssign(itemList, height, lineObject["horizontalList"])

        self._keyTextAssign(itemList, lineObject["horizontalList"])

        itemList = self._captionLetterJoin(itemList, height, lineObject)

        itemBeforeList = itemList

        itemList = self._unitAbove(itemList, height)

        itemList = self._captionRemove(itemList, height, lineObject, self._captionCollect(itemBeforeList, itemList))

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

            if anchorObject["type"] == "row" and len(keyList) == 0:
                keyList = self._keyRightCollect(anchorObject, itemList, usedList, height, lineObject)

            rowObject = self._rowFind(keyList, anchorObject)

            keyList = self._keyExtend(keyList, itemList, anchorObject["bbox"], height, lineObject["horizontalList"], rowList, anchorObject["bbox"][2], rowObject, lineObject["verticalList"])

            pairList.append(self._pairBuild(anchorObject, keyList, mergeObject["verticalList"], height, lineObject["verticalList"], lineObject["horizontalList"]))

            usedList.append(anchorObject)

            for b in range(len(keyList)):
                usedList.append(keyList[b])

        pairList = self._columnValueMerge(pairList, itemList, height, lineObject["horizontalList"])

        pairList = self._pairOrder(pairList, lineObject, height)

        sectionUsedList = []

        for a in range(len(pairList)):
            for b in range(len(pairList[a]["sectionList"])):
                if pairList[a]["sectionList"][b] not in sectionUsedList:
                    sectionUsedList.append(pairList[a]["sectionList"][b])

        restList = []
        outsideLineList = []

        for a in range(len(itemList)):
            if itemList[a] not in usedList:
                restList.append({"text": self._spaceNormalize(itemList[a]["text"]), "bbox": itemList[a]["bbox"], "page": numberPage, "isMark": itemList[a].get("isMark", False), "isOption": itemList[a].get("isOption", False), "isBoxOption": itemList[a].get("isBoxOption", False), "circleIndex": itemList[a].get("circleIndex", -1), "isOutside": itemList[a].get("isOutside", False), "detectionIndex": itemList[a].get("detectionIndex", -1 - a), "style": itemList[a].get("style", "")})

        cellPairList = []

        restList = self._cellPairBuild(self._cellStackMerge(self._outsideLineBuild(restList, outsideLineList, height), lineObject, height, itemList), lineObject, height, itemList, mergeObject["verticalList"], cellPairList)

        restList = self._restRemove(restList, self._cellHeaderBuild(restList, mergeObject["verticalList"], sectionUsedList, height, lineObject, False, itemList, cellPairList))

        textPairObject = self._textPairBuild(restList, mergeObject["verticalList"], height, lineObject["verticalList"], lineObject["horizontalList"], itemList)

        textPairObject["pairList"] = cellPairList + textPairObject["pairList"]

        self._sectionUsedAppend(textPairObject["pairList"], sectionUsedList)

        headerPairList = []

        restFreeList = self._lineFreeList(restList, textPairObject["lineItemList"])

        restHeaderList = self._cellHeaderBuild(restFreeList, mergeObject["verticalList"], sectionUsedList, height, lineObject, True, itemList, headerPairList)

        restHeaderList = restHeaderList + self._enclosedPairBuild(self._restRemove(restFreeList, restHeaderList), height, mergeObject["verticalList"], lineObject, headerPairList)

        isAdjacent = True

        while isAdjacent:
            restAdjacentList = self._cellAdjacentBuild(self._restRemove(restFreeList, restHeaderList), height, lineObject, itemList, mergeObject["verticalList"], headerPairList, pairList + cellPairList)

            restHeaderList = restHeaderList + restAdjacentList

            isAdjacent = len(restAdjacentList) > 0

        restHeaderList = restHeaderList + self._cellEmptyBuild(self._restRemove(restFreeList, restHeaderList), height, lineObject, itemList, mergeObject["verticalList"], headerPairList)

        if len(headerPairList) > 0:
            textPairObject = self._textPairBuild(self._restRemove(restList, restHeaderList), mergeObject["verticalList"], height, lineObject["verticalList"], lineObject["horizontalList"], itemList)

            textPairObject["pairList"] = cellPairList + textPairObject["pairList"] + headerPairList

        self._sectionUsedAppend(textPairObject["pairList"], sectionUsedList)

        titleFreeList = []

        for a in range(len(mergeObject["verticalList"])):
            if mergeObject["verticalList"][a] not in sectionUsedList:
                titleFreeList.append(mergeObject["verticalList"][a])

        titlePairList = []

        restTitleList = self._cellAdjacentBuild(titleFreeList + self._lineFreeList(self._restRemove(restList, restHeaderList), textPairObject["lineItemList"]), height, lineObject, itemList, mergeObject["verticalList"], titlePairList, pairList + cellPairList + headerPairList)

        if len(titlePairList) > 0:
            textPairObject = self._textPairBuild(self._restRemove(restList, restHeaderList + restTitleList), mergeObject["verticalList"], height, lineObject["verticalList"], lineObject["horizontalList"], itemList)

            textPairObject["pairList"] = cellPairList + textPairObject["pairList"] + headerPairList

        sectionUsedList = sectionUsedList + restTitleList

        sectionUsedList = sectionUsedList + self._cellEmptyBuild(self._restRemove(titleFreeList, restTitleList), height, lineObject, itemList, mergeObject["verticalList"], titlePairList)

        linePairList = []

        textPairObject["lineItemList"] = self._lineColumnPair(textPairObject["lineItemList"], pairList, height, mergeObject["verticalList"], lineObject, linePairList)

        pairList = self._pairRowAttach(pairList + textPairObject["pairList"] + titlePairList + linePairList, lineObject["horizontalList"], outsideLineList, numberPage, height, lineObject["verticalList"])

        pairList = pairList + optionObject["pairList"] + fieldPairList

        self._sectionInherit(pairList)

        pairList = self._pairOrder(pairList, lineObject, height)

        restList = list(outsideLineList)

        lineObjectPage = lineObject

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

                    bboxSpanList = [0, max(lastObject["bbox"][1], bboxList[1]), 0, min(lastObject["bbox"][3], bboxList[3])]

                    isWall = self._wallCheck(lineObjectPage["verticalList"], lastObject["bbox"][2] - height * self.levelMargin, bboxList[0] + height * self.levelMargin, bboxSpanList)

                    if isTitle == False and isWall == False and self._lineSameCheck(lastObject["bbox"], bboxList) and unicodedata.category(segmentLineList[a]["text"][0:1] or " ") == "Po":
                        lastObject["textList"][len(lastObject["textList"]) - 1] = self._textAppend(f"{lastObject['textList'][len(lastObject['textList']) - 1]} ", segmentLineList[a]["text"])
                        lastObject["bbox"] = [lastObject["bbox"][0], min(lastObject["bbox"][1], bboxList[1]), bboxList[2], max(lastObject["bbox"][3], bboxList[3])]

                        continue

                    if isTitle == False and bboxList[0] - lastObject["bbox"][2] <= height * self.levelLineJoin and isWall == False:
                        lastObject["textList"].append(segmentLineList[a]["text"])
                        lastObject["bbox"] = [lastObject["bbox"][0], min(lastObject["bbox"][1], bboxList[1]), bboxList[2], max(lastObject["bbox"][3], bboxList[3])]

                        continue

                groupList.append({"textList": [segmentLineList[a]["text"]], "bbox": list(bboxList)})

            for a in range(len(groupList)):
                restList.append({"text": " | ".join(groupList[a]["textList"]), "bbox": groupList[a]["bbox"], "isJoin": len(groupList[a]["textList"]) > 1})

        for a in range(len(mergeObject["verticalList"])):
            if mergeObject["verticalList"][a] not in sectionUsedList:
                restList.append({"text": mergeObject["verticalList"][a]["text"], "bbox": mergeObject["verticalList"][a]["bbox"], "page": numberPage})

        self._unitRowAssign(pairList)

        self._keyQualifierAssign(pairList, height)

        splitObject = self._keyDuplicateSplit(pairList, restList, height)

        pairList = splitObject["pairList"]

        headerObject = self._groupHeaderAssign(pairList, splitObject["restList"], height, lineObjectPage, itemList)

        pairList = headerObject["pairList"]
        restList = headerObject["restList"]

        restList = self._restRemove(restList, self._cellEmptyBuild(restList, height, lineObjectPage, itemList, mergeObject["verticalList"], pairList))

        restList = self._lineFieldBuild(restList, pairList, itemList, lineObjectPage, height)

        noteObject = self._rowNoteAssign(pairList, restList, lineObjectPage["horizontalList"])

        pairList = noteObject["pairList"]
        restList = noteObject["restList"]

        restList = self._unitCaptionAssign(restList, height, pairList, lineObjectPage)

        for a in range(len(matrixList)):
            restObject = {"text": matrixList[a].get("text", ""), "bbox": matrixList[a]["bbox"], "page": numberPage}

            if "lineList" in matrixList[a]:
                restObject["lineList"] = matrixList[a]["lineList"]

            restList.append(restObject)

        restList.sort(key=lambda itemObject: (int(itemObject["bbox"][1] / (height * self.levelLineBucket)), itemObject["bbox"][0]))

        self._rowIdComplete(pairList)

        if len(bandTitleList) > 0:
            return "\n".join(self._bandWrite(pairList, restList, bandTitleList, height))

        return "\n".join(self._tableWrite(pairList, restList))

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

            font = elementObject["fontName"].split("+")[-1]

            itemList.append({"text": elementObject["text"], "bbox": [elementObject["x0"] * scale, elementObject["y0"] * scale, elementObject["x1"] * scale, elementObject["y1"] * scale], "isVertical": elementObject["isVertical"], "charList": charList, "page": numberPage, "font": font, "style": f"{font}|{elementObject['fontSize']}", "fieldIndex": elementObject.get("fieldIndex", 0)})

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

    def _heightWidthMedian(self, bboxList):
        bboxSortedList = sorted(bboxList, key=lambda bboxObject: bboxObject[3] - bboxObject[1])

        widthTotal = 0

        for a in range(len(bboxSortedList)):
            widthTotal += bboxSortedList[a][2] - bboxSortedList[a][0]

        width = 0

        for a in range(len(bboxSortedList)):
            width += bboxSortedList[a][2] - bboxSortedList[a][0]

            if width * 2 >= widthTotal:
                return bboxSortedList[a][3] - bboxSortedList[a][1]

        return 0

    def _boxFraction(self, tablePageList, bboxList):
        height = self._heightWidthMedian(bboxList)

        countBox = 0
        countCell = 0

        for a in range(len(tablePageList)):
            for b in range(len(tablePageList[a]["cellList"])):
                coordinateList = tablePageList[a]["cellList"][b]["coordinate"]

                countCell += 1

                width = coordinateList[2] - coordinateList[0]
                heightCell = coordinateList[3] - coordinateList[1]

                if max(width, heightCell) <= height * self.levelModuleBoxSize and abs(width - heightCell) <= max(width, heightCell) * self.levelModuleBoxSquare:
                    countBox += 1

        if countCell == 0:
            return 0

        return countBox / countCell

    def pageCheck(self, tablePageList, areaPage, bboxList):
        areaTable = 0
        areaLargest = 0

        tableLargest = None

        bboxContentList = None

        for a in range(len(tablePageList)):
            coordinateList = tablePageList[a]["coordinate"]

            area = (coordinateList[2] - coordinateList[0]) * (coordinateList[3] - coordinateList[1])

            areaTable += area

            bboxContentList = list(coordinateList[0:4]) if bboxContentList == None else self._bboxExpand(bboxContentList, coordinateList)

            if area > areaLargest:
                areaLargest = area
                tableLargest = tablePageList[a]

        if tableLargest == None:
            return False

        areaText = 0
        areaInside = 0

        for a in range(len(bboxList)):
            area = (bboxList[a][2] - bboxList[a][0]) * (bboxList[a][3] - bboxList[a][1])

            areaText += area

            bboxContentList = self._bboxExpand(bboxContentList, bboxList[a])

            for b in range(len(tablePageList)):
                if boxCenterInsideCheck(bboxList[a], tablePageList[b]["coordinate"]):
                    areaInside += area

                    break

        areaContent = (bboxContentList[2] - bboxContentList[0]) * (bboxContentList[3] - bboxContentList[1])

        if len(bboxList) > 0 and areaTable >= areaContent * self.levelModuleArea and self._boxFraction(tablePageList, bboxList) >= self.levelModuleBox:
            return True

        if areaTable < areaPage * self.levelModuleArea or areaText == 0 or areaInside < areaText * self.levelModuleText:
            return False

        return self._gridOverlap(tableLargest["cellList"]) >= self.levelModuleOverlap

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

    def circleBuild(self, detectionList, elementList, scale):
        height = self._heightBoxMedian(self._detectionBboxList(detectionList))

        resultList = []

        for a in range(len(elementList)):
            elementObject = elementList[a]

            if elementObject["type"] != "path" or elementObject["isCurve"] == False or elementObject["isStroke"] == False:
                continue

            bboxList = [elementObject["x0"] * scale, elementObject["y0"] * scale, elementObject["x1"] * scale, elementObject["y1"] * scale]

            width = bboxList[2] - bboxList[0]
            heightPath = bboxList[3] - bboxList[1]

            if min(width, heightPath) < height * self.levelRingSizeMinimum or max(width, heightPath) > height * self.levelRingSizeMaximum or abs(width - heightPath) > max(width, heightPath) * self.levelCircleSquare:
                continue

            isDuplicate = False

            for b in range(len(resultList)):
                if self._iou(resultList[b]["bbox"], bboxList) >= self.levelDuplicate:
                    isDuplicate = True

                    break

            if isDuplicate == False:
                resultList.append({"bbox": bboxList, "isBox": False})

        return resultList + self._optionBoxBuild(elementList, scale, height)

    def _colorLightCheck(self, color):
        if len(color) != 7 or color[0] != "#":
            return False

        return (int(color[1:3], 16) * 0.299 + int(color[3:5], 16) * 0.587 + int(color[5:7], 16) * 0.114) / 255 >= self.levelColorLight

    def _optionBoxBuild(self, elementList, scale, height):
        squareList = []
        inkList = []

        for a in range(len(elementList)):
            elementObject = elementList[a]

            if elementObject["type"] == "image" or (elementObject["type"] != "text" and elementObject["isStroke"] == False and self._colorLightCheck(elementObject["color"])):
                continue

            bboxList = [elementObject["x0"] * scale, elementObject["y0"] * scale, elementObject["x1"] * scale, elementObject["y1"] * scale]

            width = bboxList[2] - bboxList[0]
            heightElement = bboxList[3] - bboxList[1]

            if elementObject["type"] == "rect" and elementObject["isStroke"] and min(width, heightElement) >= height * self.levelOptionBoxMinimum and max(width, heightElement) <= height * self.levelRingSizeMaximum and abs(width - heightElement) <= max(width, heightElement) * self.levelCircleSquare:
                squareList.append(bboxList)
            else:
                inkList.append(bboxList)

        resultList = []

        for a in range(len(squareList)):
            bboxList = squareList[a]

            size = bboxList[2] - bboxList[0]

            isIsolated = True

            for b in range(len(squareList)):
                bboxOtherList = squareList[b]

                if b == a or self._iou(bboxList, bboxOtherList) >= self.levelDuplicate:
                    continue

                if self._overlap(bboxList[1], bboxList[3], bboxOtherList[1], bboxOtherList[3]) > 0 and bboxOtherList[0] < bboxList[2] + size * self.levelOptionBoxGap and bboxOtherList[2] > bboxList[0] - size * self.levelOptionBoxGap:
                    isIsolated = False

                    break

            if isIsolated == False:
                continue

            isMark = False

            isSwatch = False

            for b in range(len(inkList)):
                if self._iou(inkList[b], bboxList) >= self.levelDuplicate:
                    isSwatch = True

                    break

            if isSwatch:
                continue

            for b in range(len(inkList)):
                centerX = (inkList[b][0] + inkList[b][2]) / 2
                centerY = (inkList[b][1] + inkList[b][3]) / 2

                if centerX > bboxList[0] and centerX < bboxList[2] and centerY > bboxList[1] and centerY < bboxList[3] and inkList[b][0] >= bboxList[0] - size * self.levelOptionBoxGap and inkList[b][2] <= bboxList[2] + size * self.levelOptionBoxGap:
                    isMark = True

                    break

            isDuplicate = False

            for b in range(len(resultList)):
                if self._iou(resultList[b]["bbox"], bboxList) >= self.levelDuplicate:
                    isDuplicate = True

            if isDuplicate == False:
                resultList.append({"bbox": bboxList, "isBox": True, "isMark": isMark})

        return resultList

    def _optionBoxApply(self, itemList, circleList):
        for a in range(len(circleList)):
            if circleList[a].get("isBox", False) == False:
                continue

            bboxList = circleList[a]["bbox"]

            size = bboxList[2] - bboxList[0]

            itemBest = None
            gapBest = -1

            for b in range(len(itemList)):
                bboxItemList = itemList[b]["bbox"]

                if self._overlap(bboxList[1], bboxList[3], bboxItemList[1], bboxItemList[3]) <= 0:
                    continue

                gap = bboxItemList[0] - bboxList[2]

                if gap < -size * self.levelOptionBoxGap:
                    gap = bboxList[0] - bboxItemList[2]

                    if gap < -size * self.levelOptionBoxGap:
                        continue

                    gap += size * self.levelOptionBoxLabel

                if gap > size * self.levelOptionBoxLabel * 2:
                    continue

                if itemBest == None or gap < gapBest:
                    itemBest = itemList[b]
                    gapBest = gap

            if itemBest != None:
                itemBest["isOption"] = True
                itemBest["isBoxOption"] = True

                if circleList[a]["isMark"]:
                    itemBest["isMark"] = True

    def optionTextApply(self, itemList, elementList, scale):
        if len(itemList) == 0:
            return itemList

        boxList = self._optionBoxBuild(elementList, scale, self._heightMedian(itemList))

        removeList = []

        for a in range(len(boxList)):
            bboxList = boxList[a]["bbox"]

            size = bboxList[2] - bboxList[0]

            itemBest = None
            gapBest = -1

            isRight = True

            for b in range(len(itemList)):
                bboxItemList = itemList[b]["bbox"]

                centerX = (bboxItemList[0] + bboxItemList[2]) / 2
                centerY = (bboxItemList[1] + bboxItemList[3]) / 2

                if centerX > bboxList[0] and centerX < bboxList[2] and centerY > bboxList[1] and centerY < bboxList[3]:
                    removeList.append(itemList[b])

                    continue

                if self._lineSameCheck(bboxList, bboxItemList) == False:
                    continue

                gap = bboxItemList[0] - bboxList[2]

                isItemRight = True

                if gap < -size * self.levelOptionBoxGap:
                    gap = bboxList[0] - bboxItemList[2]

                    if gap < -size * self.levelOptionBoxGap:
                        continue

                    gap += size * self.levelOptionBoxLabel

                    isItemRight = False

                if gap > size * self.levelOptionBoxLabel * 2:
                    continue

                if itemBest == None or gap < gapBest:
                    itemBest = itemList[b]
                    gapBest = gap

                    isRight = isItemRight

            if itemBest == None:
                continue

            textOption = self.textMark if boxList[a]["isMark"] else self.textOption

            itemBest["text"] = f"{textOption} {itemBest['text']}" if isRight else f"{itemBest['text']} {textOption}"

        return self._restRemove(itemList, removeList)

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

    def _segmentInsideCheck(self, bboxSegmentList, bboxContextList, bboxList):
        area = (bboxSegmentList[2] - bboxSegmentList[0]) * (bboxSegmentList[3] - bboxSegmentList[1])

        for a in range(len(bboxContextList)):
            bboxOtherList = bboxContextList[a]

            areaInside = max(0, min(bboxOtherList[2], bboxSegmentList[2]) - max(bboxOtherList[0], bboxSegmentList[0])) * max(0, min(bboxOtherList[3], bboxSegmentList[3]) - max(bboxOtherList[1], bboxSegmentList[1]))

            if bboxOtherList is not bboxList and areaInside >= area * self.levelContain:
                return True

        return False

    def _boxCollect(self, bboxTargetList, bboxContextList, imageInk, height, lineObject):
        boxList = []

        for a in range(len(bboxTargetList)):
            bboxList = bboxTargetList[a]

            isVertical = bboxList[3] - bboxList[1] > (bboxList[2] - bboxList[0]) * self.levelVerticalAspect

            isContainer = False

            for b in range(len(bboxContextList)):
                bboxOtherList = bboxContextList[b]

                areaInside = max(0, min(bboxOtherList[2], bboxList[2]) - max(bboxOtherList[0], bboxList[0])) * max(0, min(bboxOtherList[3], bboxList[3]) - max(bboxOtherList[1], bboxList[1]))

                if bboxOtherList is not bboxList and areaInside >= (bboxOtherList[2] - bboxOtherList[0]) * (bboxOtherList[3] - bboxOtherList[1]) * self.levelContain:
                    isContainer = True

                    break

            lineList = [bboxList] if isVertical or isContainer else self._lineSplit(bboxList, imageInk, height)

            for b in range(len(lineList)):
                if isVertical == False:
                    lineList[b] = self._overlapTrim(lineList[b], bboxContextList)

                splitList = self._boxSplit(lineList[b], imageInk, isVertical, height, lineObject["horizontalList"] if isVertical else lineObject["verticalList"])

                for c in range(len(splitList)):
                    if isVertical and self._segmentInsideCheck(splitList[c]["bbox"], bboxContextList, bboxList):
                        continue

                    boxList.append({"bbox": splitList[c]["bbox"], "bboxRecognize": splitList[c]["bboxRecognize"], "isVertical": isVertical, "index": a})

        return boxList

    def _keyAssign(self, boxList, detectionList):
        for a in range(len(boxList)):
            boxList[a]["key"] = (detectionList[boxList[a]["index"]]["coordinate"][0][1], detectionList[boxList[a]["index"]]["coordinate"][0][0])

        return boxList

    def _boxRecognize(self, boxList, recognition, image):
        quadList = []

        for a in range(len(boxList)):
            bboxRecognizeList = boxList[a]["bboxRecognize"]

            quadList.append([[bboxRecognizeList[0], bboxRecognizeList[1]], [bboxRecognizeList[2], bboxRecognizeList[1]], [bboxRecognizeList[2], bboxRecognizeList[3]], [bboxRecognizeList[0], bboxRecognizeList[3]]])

        recognitionList = recognition.execute(quadList, image)

        for a in range(len(boxList)):
            boxList[a]["text"] = recognitionList[a]["text"]

            boxList[a]["charPositionList"] = self._charPositionBuild(boxList[a]["isVertical"], boxList[a]["bboxRecognize"], recognitionList[a]["positionList"])

        return boxList

    def _charPositionBuild(self, isVertical, bboxList, positionList):
        resultList = []

        if isVertical:
            return resultList

        width = bboxList[2] - bboxList[0]

        for a in range(len(positionList)):
            resultList.append({"text": positionList[a]["text"], "start": bboxList[0] + positionList[a]["start"] * width, "end": bboxList[0] + positionList[a]["end"] * width})

        return resultList

    def _speckRemove(self, itemList, height):
        resultList = []

        for a in range(len(itemList)):
            width = itemList[a]["bbox"][2] - itemList[a]["bbox"][0]
            heightItem = itemList[a]["bbox"][3] - itemList[a]["bbox"][1]

            if width > height * self.levelSpeckWidth and max(width, heightItem) >= height * self.levelSpeckSide:
                resultList.append(itemList[a])

        return resultList

    def itemImageBuild(self, detectionList, image, recognition, watermarkObject, numberPage):
        bboxDetectionList = self._detectionBboxList(detectionList)

        height = self._heightBoxMedian(bboxDetectionList)

        lineObject = self._lineCollect(image, height)

        imageClean = self._dashErase(image, lineObject["dashList"])

        imageInk = imageInkBuild(imageClean)

        boxList = self._boxCollect(bboxDetectionList, bboxDetectionList, imageInk, height, lineObject)

        ringList = self._ringCollect(image, height)

        boxList = self._boxRecognize(boxList, recognition, imageClean)

        if watermarkObject["isFound"]:
            boxList = self._keyAssign(boxList, detectionList)

            boxKeepList = []
            bboxContextList = []

            for a in range(len(boxList)):
                if watermarkObject["isKeepList"][boxList[a]["index"]]:
                    boxKeepList.append(boxList[a])

            for a in range(len(bboxDetectionList)):
                if watermarkObject["isKeepList"][a]:
                    bboxContextList.append(bboxDetectionList[a])

            bboxZoneList = self._detectionBboxList(watermarkObject["detectionZoneList"])

            imageZoneClean = self._dashErase(watermarkObject["image"], lineObject["dashList"])

            boxZoneList = self._keyAssign(self._boxRecognize(self._boxCollect(bboxZoneList, bboxContextList + bboxZoneList, imageInkBuild(imageZoneClean), height, lineObject), recognition, imageZoneClean), watermarkObject["detectionZoneList"])

            for a in range(len(boxZoneList)):
                boxZoneList[a]["index"] += len(detectionList)

            boxList = sorted(boxKeepList + boxZoneList, key=lambda item: item["key"])

        itemList = []

        for a in range(len(boxList)):
            text = boxList[a]["text"]

            if len(text.strip()) == 0:
                continue

            itemList.append({"text": text, "bbox": boxList[a]["bbox"], "isVertical": boxList[a]["isVertical"], "charList": [], "charPositionList": boxList[a]["charPositionList"], "page": numberPage, "detectionIndex": boxList[a]["index"]})

        itemList = self._speckRemove(itemList, height)

        itemList = self._ringInterior(itemList, ringList, imageClean, imageInk, recognition)

        self._emBoxBuild(itemList)

        return {"itemList": itemList, "ringList": ringList, "lineObject": lineObject}

    def __init__(self):
        self.reference = reference.Reference()

        self.levelColorLight = 0.95
        self.countMatrixMinimum = 3
        self.levelDisplaySize = 2.0
        self.countLeaderMinimum = 3
        self.countRowId = 4
        self.levelSelfField = 1.0
        self.levelSelfFieldRatio = 0.5
        self.levelFrameRule = 0.9
        self.levelBandTitle = 1.2
        self.levelLineSame = 0.5

        self.levelModuleArea = 0.6
        self.levelModuleText = 0.9
        self.levelModuleOverlap = 0.2
        self.levelModuleBox = 0.3
        self.levelModuleBoxSize = 3.0
        self.levelModuleBoxSquare = 0.2
        self.levelLineExtend = 0.5
        self.levelLineDouble = 1.7
        self.levelLineMiddle = 0.3
        self.levelLineValley = 0.4
        self.levelContain = 0.9
        self.levelRuleLength = 1.5
        self.levelRuleLengthHorizontal = 1.2
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
        self.levelStackGap = 1.5
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
        self.levelUnitAlign = 1.0
        self.levelHeaderGap = 2.0
        self.countHeaderRow = 0
        self.levelUnitSize = 0.75
        self.levelUnitIsolate = 0.6
        self.levelStrikeBand = 0.25
        self.levelStrikeCover = 0.8
        self.levelQualifierGap = 2.0
        self.levelCircleSquare = 0.2
        self.levelOptionBoxMinimum = 0.5
        self.levelOptionBoxGap = 0.5
        self.levelOptionBoxLabel = 1.0
        self.levelOptionLineGap = 0.5
        self.levelCellBelow = 1.5
        self.countLineSplit = 4
        self.textMark = "[x]"
        self.textOption = "[ ]"
        self.countRowMinimum = 3
        self.countRowDigit = 3
        self.countRowMissing = 1
        self.levelRowSlot = 2.0
        self.countLetterSpace = 3
        self.countLabelMinimum = 2
        self.levelVerticalGap = 4.0
        self.levelVerticalSize = 0.3
        self.levelPitch = 0.25
        self.levelPitchRatio = 1.8
        self.levelGapOutlier = 3.0
        self.levelBandOverlap = 0.3
        self.levelBandHeight = 2.75
        self.levelBandItem = 1.5
        self.countVerticalMinimum = 3
        self.countStackLetter = 2
        self.countCaptionMaximum = 5
        self.levelCaptionOverlap = 0.5
        self.levelRuleFraction = 3.0
        self.levelCellLabel = 5.0
        self.levelCellInside = 0.5
        self.levelCellDouble = 0.3
        self.levelRuleEnd = 0.5
        self.levelCellValue = 2.0
        self.levelCellReach = 2.0
        self.countCellRow = 2
        self.countCellHeaderRow = 3
        self.countLabelRowCell = 3
        self.levelBandSame = 0.5
        self.levelLabelPitch = 1.1
        self.levelLabelEmpty = 3.0
        self.countRowColumn = 3
        self.countAttachKey = 3
        self.levelCellLeftProbe = 0.3
        self.levelSeparatorGap = 2.0
        self.levelSparseGap = 3.0
        self.countSparseMinimum = 2
        self.levelTableDouble = 1.5
        self.levelWallCutLength = 3.0
        self.levelWallCutHeight = 0.6
        self.countPartIndex = 100000
        self.levelCellHeaderBand = 1.5
        self.levelSpeckWidth = 0.1
        self.levelSpeckSide = 0.3
        self.levelTitleStack = 2.0
        self.levelTableRule = 0.5
        self.countStackDouble = 2
        self.levelStackWidth = 2.5
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
        self.levelRingStroke = 0.3
        self.levelRingStrokeInk = 0.5
        self.levelTrimGap = 0.15
        self.levelStrokeFlat = 0.5
        self.levelTrimWidth = 0.5
        self.levelTrimOverlap = 0.5
        self.levelDuplicate = 0.6
        self.levelSize = 0.3
        self.levelLine = 0.4
        self.levelOverlap = 0.3
        self.levelGap = 1.0
