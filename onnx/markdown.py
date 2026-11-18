import sys
import icu

sys.dont_write_bytecode = True

# Source
from helper import sizeDominantCalculate, privateUseCheck, tokenFirstLength, textNormalize, spacelessCheck, whitespaceCheck, spaceSkipCheck, sentenceEndCheck, boxCenterInsideCheck, boxIntersection, rangeOverlapRatio, flowGapCalculate, levelColumnOverlap, levelSpaceGap, levelTitleSize, levelTitleLength, textOptionMark, textOptionEmpty, boxExpand, textCutCheck, textBullet, separatorOption, categoryContainCheck, categoryWordList

class Markdown:
    def _textJoin(self, textList):
        result = ""

        for a in range(len(textList)):
            if len(result) == 0:
                result = textList[a]

                continue

            if whitespaceCheck(result[-1:]) or whitespaceCheck(textList[a][0:1]):
                result += textList[a]

                continue

            if spacelessCheck(result[-1:]) and spacelessCheck(textList[a][0:1]):
                result += textList[a]

                continue

            result += f"{self.separatorText}{textList[a]}"

        return result

    def _textEscape(self, text):
        return text.replace("<", "\\<")

    def _gridSize(self, cellList):
        countRow = 0
        countColumn = 0

        for a in range(len(cellList)):
            if cellList[a]["rowIndex"] + cellList[a]["rowSpan"] > countRow:
                countRow = cellList[a]["rowIndex"] + cellList[a]["rowSpan"]

            if cellList[a]["columnIndex"] + cellList[a]["columnSpan"] > countColumn:
                countColumn = cellList[a]["columnIndex"] + cellList[a]["columnSpan"]

        return {"countRow": countRow, "countColumn": countColumn}

    def _gridEmpty(self, countRow, countColumn):
        resultList = []

        for a in range(countRow):
            rowList = []

            for b in range(countColumn):
                rowList.append(self.textCellEmpty)

            resultList.append(rowList)

        return resultList

    def _gridPut(self, gridList, rowIndex, columnIndex, text):
        current = gridList[rowIndex][columnIndex]

        if current == self.textCellEmpty or current in text:
            gridList[rowIndex][columnIndex] = text
        elif text not in current:
            gridList[rowIndex][columnIndex] = f"{current} {text}"

    def _gridSpanFill(self, cellList, gridList):
        for a in range(len(cellList)):
            text = self._cellEscape(cellList[a]["text"])

            if len(text) == 0:
                continue

            for b in range(1, cellList[a]["rowSpan"]):
                if gridList[cellList[a]["rowIndex"] + b][cellList[a]["columnIndex"]] == self.textCellEmpty:
                    gridList[cellList[a]["rowIndex"] + b][cellList[a]["columnIndex"]] = text

    def _gridCellBuild(self, cellList):
        sizeObject = self._gridSize(cellList)

        resultList = self._gridEmpty(sizeObject["countRow"], sizeObject["countColumn"])

        for a in range(len(cellList)):
            text = self._cellEscape(cellList[a]["text"])

            if len(text) == 0:
                continue

            self._gridPut(resultList, cellList[a]["rowIndex"], cellList[a]["columnIndex"], text)

        self._gridSpanFill(cellList, resultList)

        return resultList

    def _cellEscape(self, text):
        return self._textEscape(text.replace(self.separatorCell, self.separatorCellEscaped).replace(self.separatorLine, self.separatorText).strip())

    def _tableWrite(self, headerList, gridList):
        separatorList = []

        for a in range(len(headerList)):
            separatorList.append("---")

        lineList = [self._rowWrite(headerList), self._rowWrite(separatorList)]

        for a in range(len(gridList)):
            lineList.append(self._rowWrite(gridList[a]))

        return self.separatorLine.join(lineList)

    def _gridHeaderWrite(self, gridList, isHeader=False):
        headerObject = self._gridHeaderSplit(gridList, isHeader)

        table = self._tableWrite(headerObject["headerList"], headerObject["bodyList"])

        if len(headerObject["captionList"]) == 0:
            return table

        return self.separatorBlock.join(headerObject["captionList"] + [table])

    def _gridHeaderSplit(self, gridList, isHeader):
        emptyList = []

        for a in range(len(gridList[0])):
            emptyList.append(self.textCellEmpty)

        resultObject = {"captionList": [], "headerList": emptyList, "bodyList": gridList}

        if len(gridList) < 2:
            return resultObject

        if len(gridList[0]) >= self.countHeaderColumnMinimum:
            for a in range(min(self.countHeaderSearch, len(gridList) - 1)):
                if a > 0 and self._rowCaptionCheck(gridList[a - 1]) == False:
                    break

                countHeader = self._headerCount(gridList, a)

                isText = True

                for b in range(countHeader):
                    if self._rowTextCheck(gridList[a + b]) == False:
                        isText = False

                if isText and (self._headerColumnCheck(self._headerRowBuild(gridList, a, countHeader), gridList[a + countHeader:]) or self._bodyEmptyCheck(gridList[a], gridList[a + countHeader:])):
                    return self._gridHeaderBuild(gridList, a, countHeader)

        if isHeader:
            return self._gridHeaderBuild(gridList, 0, self._headerCount(gridList, 0))

        return resultObject

    def _gridHeaderBuild(self, gridList, index, countHeader):
        captionList = []

        for a in range(index):
            textList = []

            for b in range(len(gridList[a])):
                if gridList[a][b] != self.textCellEmpty:
                    textList.append(gridList[a][b])

            captionList.append(self.separatorText.join(textList))

        return {"captionList": captionList, "headerList": self._headerRowBuild(gridList, index, countHeader), "bodyList": gridList[index + countHeader:]}

    def _headerCount(self, gridList, index):
        if index + 2 < len(gridList) and self.textCellEmpty in gridList[index] and self._rowTextCheck(gridList[index + 1]):
            return 2

        return 1

    def _headerRowBuild(self, gridList, index, countHeader):
        if countHeader == 2:
            return self._headerJoin(gridList[index], gridList[index + 1])

        return list(gridList[index])

    def _rowCaptionCheck(self, rowList):
        count = 0

        for a in range(len(rowList)):
            if rowList[a] != self.textCellEmpty:
                count += 1

        return count <= self.countCaptionCell

    def _rowTextCheck(self, rowList):
        count = 0

        for a in range(len(rowList)):
            if rowList[a] == self.textCellEmpty:
                continue

            count += 1

            if self._numberCellCheck(rowList[a]):
                return False

        return count >= min(self.countHeaderColumn, len(rowList))

    def _numberCellCheck(self, text):
        count = 0

        for a in range(len(text)):
            if icu.Char.charType(text[a]) == icu.UCharCategory.DECIMAL_DIGIT_NUMBER:
                count += 1

        return count * 2 > len(text)

    def _headerJoin(self, rowFirstList, rowSecondList):
        resultList = []

        textGroup = self.textCellEmpty

        for a in range(len(rowFirstList)):
            if rowFirstList[a] != self.textCellEmpty:
                textGroup = rowFirstList[a]

            if rowSecondList[a] == self.textCellEmpty or rowSecondList[a] == textGroup:
                resultList.append(textGroup)
            elif textGroup == self.textCellEmpty:
                resultList.append(rowSecondList[a])
            else:
                resultList.append(self._textJoin([textGroup, rowSecondList[a]]))

        return resultList

    def _headerColumnCheck(self, headerList, bodyList):
        if len(headerList) < self.countHeaderColumn:
            return self._headerPairCheck(bodyList)

        isRepeat = False

        for a in range(len(headerList)):
            if headerList[a] == self.textCellEmpty:
                continue

            valueList = []
            count = 0
            countNumber = 0

            for b in range(len(bodyList)):
                if bodyList[b][a] == self.textCellEmpty:
                    continue

                count += 1

                if self._numberCellCheck(bodyList[b][a]):
                    countNumber += 1

                if bodyList[b][a] in valueList:
                    isRepeat = True

                valueList.append(bodyList[b][a])

            if count > 0 and countNumber * 2 >= count:
                return True

            if headerList[a] in valueList:
                return False

        return isRepeat

    def _bodyEmptyCheck(self, headerList, bodyList):
        if self.textCellEmpty in headerList or len(bodyList) == 0:
            return False

        for a in range(len(bodyList)):
            for b in range(len(bodyList[a])):
                if bodyList[a][b] != self.textCellEmpty:
                    return False

        return True

    def _headerPairCheck(self, bodyList):
        if len(bodyList) < self.countHeaderRow:
            return False

        for a in range(len(bodyList)):
            if bodyList[a][1] != self.textCellEmpty and self._numberCellCheck(bodyList[a][1]) == False:
                return False

        return True

    def _rowWrite(self, textList):
        return f"{self.separatorCell} {f' {self.separatorCell} '.join(textList)} {self.separatorCell}"

    def _secondaryAppend(self, blockList, secondaryList):
        if len(secondaryList) == 0:
            return blockList

        return blockList + ["> **SECONDARY ELEMENT**"] + secondaryList

    def execute(self, resultObject, extension):
        return self.builderObject[extension].execute(resultObject, extension)

    def __init__(self, extensionObject, office):
        self.separatorText = " "
        self.separatorLine = "\n"
        self.separatorBlock = "\n\n"
        self.separatorCell = "|"
        self.separatorCellEscaped = "\\|"

        self.countHeaderColumn = 3
        self.countHeaderColumnMinimum = 2
        self.countHeaderRow = 2
        self.countHeaderSearch = 3
        self.countCaptionCell = 1
        
        self.textCellEmpty = "​"

        self.textOptionList = [textOptionEmpty, textOptionMark]

        self.builderObject = {}

        builderRaster = self.Raster(self)

        for a in range(len(extensionObject["image"])):
            self.builderObject[extensionObject["image"][a]] = builderRaster

        for a in range(len(extensionObject["pdf"])):
            self.builderObject[extensionObject["pdf"][a]] = builderRaster

        builderOffice = self.Office(self, office)

        for a in range(len(extensionObject["office"])):
            self.builderObject[extensionObject["office"][a]] = builderOffice

    class Raster:
        def _labelRefine(self, layoutList, itemList, directionObject):
            sizeBody = self._sizeDominant(itemList)

            if sizeBody == 0:
                return

            sizeBest = 0
            indexTitle = -1

            for a in range(len(layoutList)):
                label = layoutList[a]["label"]

                if label not in self.labelRefineList or layoutList[a]["flow"] != "main":
                    continue

                itemInsideList = self._itemInsideCollect(itemList, layoutList[a]["page"], layoutList[a]["bbox"])

                size = self._sizeDominant(itemInsideList)

                if size == 0:
                    continue

                lineList = self._lineGroup(itemInsideList, directionObject)

                isListMark = self._listMarkCheck(self._lineText(lineList[0], directionObject))

                if label in self.labelPrefixObject:
                    isBold = self._boldCheck(itemInsideList)

                    if isListMark or (isBold != True and size < sizeBody) or (isBold == False and size == sizeBody):
                        layoutList[a]["label"] = "text"
                elif isListMark == False and self._titleCheck(lineList, directionObject, size, sizeBody):
                    layoutList[a]["label"] = "paragraph_title"

                if layoutList[a]["label"] not in self.labelPrefixObject:
                    continue

                if layoutList[a]["page"] == layoutList[0]["page"] and size > sizeBest:
                    sizeBest = size
                    indexTitle = a

            for a in range(len(layoutList)):
                if layoutList[a]["label"] == "doc_title" and a != indexTitle:
                    layoutList[a]["label"] = "paragraph_title"

            if indexTitle >= 0 and sizeBest >= sizeBody * levelTitleSize:
                layoutList[indexTitle]["label"] = "doc_title"

            for a in range(1, len(layoutList)):
                if layoutList[a]["label"] != "paragraph_title" or layoutList[a - 1]["label"] != "doc_title" or layoutList[a]["page"] != layoutList[a - 1]["page"]:
                    continue

                isLast = True

                for b in range(a + 1, len(layoutList)):
                    if layoutList[b]["page"] == layoutList[a]["page"] and layoutList[b]["flow"] == "main":
                        isLast = False

                if isLast:
                    layoutList[a]["label"] = "text"

        def _sizeDominant(self, itemList):
            return sizeDominantCalculate(itemList)

        def _boldCheck(self, itemList):
            count = 0
            countBold = 0

            for a in range(len(itemList)):
                if itemList[a]["isBold"] == None:
                    continue

                count += len(itemList[a]["text"])

                if itemList[a]["isBold"]:
                    countBold += len(itemList[a]["text"])

            if count == 0:
                return None

            return countBold * 2 > count

        def _listMarkCheck(self, text):
            if len(text) < 2 or whitespaceCheck(text[1:2]) == False or icu.Char.isalnum(text[0:1]):
                return False

            return icu.Char.charType(text[0:1]) != icu.UCharCategory.DASH_PUNCTUATION

        def _titleCheck(self, lineList, directionObject, size, sizeBody):
            if size < sizeBody * levelTitleSize or len(lineList) > 1:
                return False

            text = self._lineText(lineList[0], directionObject)

            return len(text) <= levelTitleLength and sentenceEndCheck(text) == False

        def _lineTitleWrite(self, lineObject, directionObject, sizeBody):
            text = self._lineText(lineObject, directionObject)

            size = self._sizeDominant(lineObject["itemList"])

            if sizeBody > 0 and size > 0 and self._listMarkCheck(text) == False and self._titleCheck([lineObject], directionObject, size, sizeBody):
                return f"{self.labelPrefixObject['paragraph_title']}{text}"

            return text

        def _layoutSiblingFind(self, layoutObject, directionObject, lineObject, layoutList, itemList):
            directionPageObject = directionObject[layoutObject["page"]]

            columnList = self._axisRange(layoutObject["bbox"], directionPageObject["isVertical"] == False)
            crossList = self._axisRange(lineObject["bbox"], directionPageObject["isVertical"])

            for a in range(len(layoutList)):
                if layoutList[a] is layoutObject or layoutList[a]["page"] != layoutObject["page"] or self._pairCandidateCheck(directionObject, layoutList[a]) == False:
                    continue

                columnOtherList = self._axisRange(layoutList[a]["bbox"], directionPageObject["isVertical"] == False)

                if min(columnList[1], columnOtherList[1]) > max(columnList[0], columnOtherList[0]):
                    continue

                lineOtherList = self._lineGroup(self._itemInsideCollect(itemList, layoutList[a]["page"], layoutList[a]["bbox"]), directionObject)

                if len(lineOtherList) == 0:
                    continue

                crossOtherList = self._axisRange(lineOtherList[0]["bbox"], directionPageObject["isVertical"])

                if rangeOverlapRatio(crossList[0], crossList[1], crossOtherList[0], crossOtherList[1]) >= self.levelLineOverlap:
                    return lineOtherList[0]

            return None

        def _layoutLineSplitFind(self, lineList, layoutObject, directionObject, layoutList, itemList):
            if len(lineList) == 0:
                return -1

            lineFirstObject = self._layoutSiblingFind(layoutObject, directionObject, lineList[0], layoutList, itemList)

            if lineFirstObject == None:
                return -1

            directionPageObject = directionObject[layoutObject["page"]]

            columnFirstList = self._axisRange(lineFirstObject["bbox"], directionPageObject["isVertical"] == False)

            for a in range(1, len(lineList)):
                crossList = self._axisRange(lineList[a]["bbox"], directionPageObject["isVertical"])

                pitch = crossList[0] - self._axisRange(lineList[a - 1]["bbox"], directionPageObject["isVertical"])[0]

                pitchOther = 0

                for b in range(1, len(lineList)):
                    if b != a:
                        pitchOther = max(pitchOther, self._axisRange(lineList[b]["bbox"], directionPageObject["isVertical"])[0] - self._axisRange(lineList[b - 1]["bbox"], directionPageObject["isVertical"])[0])

                if pitchOther <= 0 or pitch < pitchOther * self.levelLineSplitPitch:
                    continue

                lineOtherObject = self._layoutSiblingFind(layoutObject, directionObject, lineList[a], layoutList, itemList)

                if lineOtherObject == None or lineOtherObject is lineFirstObject:
                    continue

                columnOtherList = self._axisRange(lineOtherObject["bbox"], directionPageObject["isVertical"] == False)

                edgeFirst = columnFirstList[1] if directionPageObject["isRightToLeft"] else columnFirstList[0]
                edgeOther = columnOtherList[1] if directionPageObject["isRightToLeft"] else columnOtherList[0]

                if abs(edgeOther - edgeFirst) <= (crossList[1] - crossList[0]) * self.levelPairAlign:
                    return a

            return -1

        def _titleContextBuild(self, layoutList, itemList, directionObject):
            titleSizeList = []

            for a in range(len(layoutList)):
                if layoutList[a]["label"] != "paragraph_title":
                    continue

                lineList = self._layoutLineList(layoutList[a], itemList, directionObject)

                if len(lineList) == 1 and self._lineBoldSizeFind(lineList[0]) > 0:
                    titleSizeList.append(self._lineBoldSizeFind(lineList[0]))

            for numberPage in directionObject:
                directionObject[numberPage]["titleSizeList"] = titleSizeList
                directionObject[numberPage]["marginStart"] = 0

            marginObject = {}

            for a in range(len(itemList)):
                if itemList[a]["page"] not in marginObject or itemList[a]["bbox"][0] < marginObject[itemList[a]["page"]]:
                    marginObject[itemList[a]["page"]] = itemList[a]["bbox"][0]

            for numberPage in marginObject:
                directionObject[numberPage]["marginStart"] = marginObject[numberPage]

        def _layoutLineList(self, layoutObject, itemList, directionObject):
            return self._lineGroup(self._itemInsideCollect(itemList, layoutObject["page"], layoutObject["bbox"]), directionObject)

        def _titleTwinFind(self, layoutObject, layoutList, itemList, directionObject):
            lineList = self._layoutLineList(layoutObject, itemList, directionObject)

            if len(lineList) != 1:
                return None

            bboxList = lineList[0]["bbox"]

            layoutTwin = None
            layoutBelow = None

            for a in range(len(layoutList)):
                bboxOtherList = layoutList[a]["bbox"]

                if layoutList[a]["label"] != "text" or layoutList[a]["page"] != layoutObject["page"]:
                    continue

                lineOtherList = self._layoutLineList(layoutList[a], itemList, directionObject)

                if len(lineOtherList) == 0:
                    continue

                if bboxOtherList[0] < layoutObject["bbox"][2] and bboxOtherList[2] > layoutObject["bbox"][0]:
                    if bboxOtherList[1] >= bboxList[1] and lineOtherList[0]["bbox"][1] - bboxList[3] < bboxList[3] - bboxList[1] and (layoutBelow == None or bboxOtherList[1] < layoutBelow["bbox"][1]):
                        layoutBelow = layoutList[a]

                    continue

                if len(lineOtherList) > 1 and rangeOverlapRatio(bboxList[1], bboxList[3], lineOtherList[0]["bbox"][1], lineOtherList[0]["bbox"][3]) >= levelColumnOverlap and self._lineStyleCheck(lineList[0], lineOtherList[0]):
                    layoutTwin = layoutList[a]

            if layoutTwin == None or layoutBelow == None:
                return None

            lineTwinList = self._layoutLineList(layoutTwin, itemList, directionObject)
            lineBelowList = self._layoutLineList(layoutBelow, itemList, directionObject)

            if rangeOverlapRatio(lineBelowList[0]["bbox"][1], lineBelowList[0]["bbox"][3], lineTwinList[1]["bbox"][1], lineTwinList[1]["bbox"][3]) < levelColumnOverlap:
                return None

            return layoutBelow

        def _layoutTitleMerge(self, layoutList, directionObject, itemList):
            resultList = []

            removeList = []

            for a in range(len(layoutList)):
                layoutObject = layoutList[a]

                layoutBelow = None

                if layoutObject["label"] == "paragraph_title" and layoutObject["flow"] == "main":
                    layoutBelow = self._titleTwinFind(layoutObject, layoutList, itemList, directionObject)

                if layoutBelow == None:
                    resultList.append(layoutObject)

                    continue

                layoutMergeObject = dict(layoutObject)
                layoutMergeObject["label"] = "text"
                layoutMergeObject["bbox"] = boxExpand(list(layoutObject["bbox"]), layoutBelow["bbox"])

                resultList.append(layoutMergeObject)

                removeList.append(layoutBelow)

            return [layoutObject for layoutObject in resultList if layoutObject not in removeList]

        def _layoutLineSplit(self, layoutList, directionObject, itemList):
            resultList = list(layoutList)

            index = 0

            while index < len(resultList):
                layoutObject = resultList[index]

                index += 1

                if self._pairCandidateCheck(directionObject, layoutObject) == False:
                    continue

                lineList = self._lineGroup(self._itemInsideCollect(itemList, layoutObject["page"], layoutObject["bbox"]), directionObject)

                indexSplit = self._layoutLineSplitFind(lineList, layoutObject, directionObject, resultList, itemList)

                if indexSplit < 0:
                    continue

                bboxList = layoutObject["bbox"]

                boundary = int((lineList[indexSplit - 1]["bbox"][3] + lineList[indexSplit]["bbox"][1]) / 2)

                layoutFirstObject = dict(layoutObject)
                layoutFirstObject["bbox"] = [bboxList[0], bboxList[1], bboxList[2], boundary]

                layoutSecondObject = dict(layoutObject)
                layoutSecondObject["bbox"] = [bboxList[0], boundary, bboxList[2], bboxList[3]]

                resultList[index - 1] = layoutFirstObject

                resultList.insert(index, layoutSecondObject)

            return resultList

        def _itemOrphanCollect(self, itemList, layoutList):
            resultList = []

            for a in range(len(itemList)):
                isInside = False

                for b in range(len(layoutList)):
                    if layoutList[b]["page"] != itemList[a]["page"]:
                        continue

                    if boxCenterInsideCheck(itemList[a]["bbox"], layoutList[b]["bbox"]) == False:
                        continue

                    isInside = True

                    break

                if isInside == False:
                    resultList.append(itemList[a])

            return resultList

        def _lineGroup(self, itemList, directionObject):
            resultList = []

            itemSortedList = sorted(itemList, key=lambda itemObject: (itemObject["page"], self._lineFlowKey(itemObject["bbox"], directionObject[itemObject["page"]])))

            for a in range(len(itemSortedList)):
                bboxList = itemSortedList[a]["bbox"]

                crossList = self._axisRange(bboxList, directionObject[itemSortedList[a]["page"]]["isVertical"])

                isAdded = False

                for b in range(len(resultList)):
                    if resultList[b]["page"] != itemSortedList[a]["page"]:
                        continue

                    if rangeOverlapRatio(crossList[0], crossList[1], resultList[b]["cross1"], resultList[b]["cross2"]) < self.levelLineOverlap:
                        continue

                    resultList[b]["cross1"] = min(resultList[b]["cross1"], crossList[0])
                    resultList[b]["cross2"] = max(resultList[b]["cross2"], crossList[1])

                    resultList[b]["bbox"] = boxExpand(resultList[b]["bbox"], bboxList)

                    resultList[b]["itemList"].append(itemSortedList[a])

                    isAdded = True

                    break

                if isAdded == False:
                    resultList.append({"page": itemSortedList[a]["page"], "cross1": crossList[0], "cross2": crossList[1], "bbox": list(bboxList), "itemList": [itemSortedList[a]]})

            return sorted(resultList, key=lambda lineObject: (lineObject["page"], self._lineFlowKey(lineObject["bbox"], directionObject[lineObject["page"]])))

        def _lineFlowKey(self, bboxList, directionPageObject):
            if directionPageObject["isVertical"]:
                return -bboxList[2]

            return bboxList[1]

        def _axisRange(self, bboxList, isVertical):
            if isVertical:
                return [bboxList[0], bboxList[2]]

            return [bboxList[1], bboxList[3]]

        def _lineFlow(self, lineObject, layoutList, directionObject):
            directionPageObject = directionObject[lineObject["page"]]

            columnLineList = self._axisRange(lineObject["bbox"], directionPageObject["isVertical"] == False)
            crossLineList = self._axisRange(lineObject["bbox"], directionPageObject["isVertical"])

            distanceBest = -1
            flowResult = "main"

            for a in range(len(layoutList)):
                if layoutList[a]["page"] != lineObject["page"]:
                    continue

                columnList = self._axisRange(layoutList[a]["bbox"], directionPageObject["isVertical"] == False)

                if min(columnLineList[1], columnList[1]) <= max(columnLineList[0], columnList[0]):
                    continue

                crossList = self._axisRange(layoutList[a]["bbox"], directionPageObject["isVertical"])

                distance = max(crossList[0] - crossLineList[1], crossLineList[0] - crossList[1], 0)

                if distanceBest >= 0 and distance >= distanceBest:
                    continue

                distanceBest = distance
                flowResult = layoutList[a]["flow"]

            return flowResult

        def _lineText(self, lineObject, directionObject, isColumnGap=True):
            directionPageObject = directionObject[lineObject["page"]]

            itemSortedList = sorted(lineObject["itemList"], key=lambda itemObject: self._itemOrderKey(itemObject["bbox"], directionPageObject))

            result = ""

            for a in range(len(itemSortedList)):
                if len(result) == 0:
                    result = itemSortedList[a]["text"]

                    continue

                gapObject = flowGapCalculate(itemSortedList[a - 1]["bbox"], itemSortedList[a]["bbox"], directionPageObject)

                if isColumnGap and gapObject["gap"] >= gapObject["size"] * self.levelColumnGap:
                    result += f" {self.markdown.separatorCell} "
                elif self._spaceCheck(itemSortedList[a - 1]["bbox"], itemSortedList[a]["bbox"], result, itemSortedList[a]["text"], directionPageObject):
                    result += self.markdown.separatorText

                result += itemSortedList[a]["text"]

            if privateUseCheck(result[0:1]):
                result = f"{textBullet}{result[1:].lstrip()}"

            return self.markdown._textEscape(result)

        def _spaceCheck(self, bboxPreviousList, bboxList, textPrevious, text, directionPageObject):
            if spaceSkipCheck(textPrevious, text):
                return False

            gapObject = flowGapCalculate(bboxPreviousList, bboxList, directionPageObject)

            return gapObject["gap"] >= gapObject["size"] * levelSpaceGap

        def _itemOrderKey(self, bboxList, directionPageObject):
            if directionPageObject["isVertical"]:
                return bboxList[1]

            if directionPageObject["isRightToLeft"]:
                return -bboxList[2]

            return bboxList[0]

        def _blockWrite(self, layoutObject, tableList, itemList, directionObject):
            label = layoutObject["label"]

            if label in self.labelPlaceholderList:
                return f"![{label}]({layoutObject['path']})"

            if label == "table":
                tableObject = self._tableFind(tableList, layoutObject)

                if tableObject != None:
                    return self._tableObjectWrite(tableObject, itemList, directionObject)

            text = self._textBuild(itemList, layoutObject["page"], layoutObject["bbox"], directionObject, label not in self.labelPrefixObject)

            if len(text) == 0:
                return ""

            if label not in self.labelPrefixObject:
                return text

            return f"{self.labelPrefixObject[label]}{self.markdown.separatorText.join(text.replace(self.markdown.separatorLine, self.markdown.separatorText).replace(self.markdown.separatorCell, self.markdown.separatorText).split())}"

        def _moduleWrite(self, layoutObject, moduleObject, moduleWrittenList):
            label = layoutObject["label"]

            if label in self.labelPlaceholderList:
                return f"![{label}]({layoutObject['path']})"

            if label != "table" or layoutObject["page"] in moduleWrittenList:
                return ""

            moduleWrittenList.append(layoutObject["page"])

            return moduleObject[layoutObject["page"]]

        def _tableFind(self, tableList, layoutObject):
            for a in range(len(tableList)):
                if tableList[a]["page"] != layoutObject["page"]:
                    continue

                if tableList[a]["bbox"] != layoutObject["bbox"]:
                    continue

                return tableList[a]

            return None

        def _tableObjectWrite(self, tableObject, itemList, directionObject):
            return self._gridWrite(self._tableGridBuild(tableObject, directionObject), self._rowBoldCheck(tableObject, itemList))

        def _rowBoldCheck(self, tableObject, itemList):
            countHeader = 0
            countHeaderBold = 0
            countBody = 0
            countBodyBold = 0

            cellList = tableObject["cellList"]

            for a in range(len(cellList)):
                itemInsideList = self._itemInsideCollect(itemList, tableObject["page"], cellList[a]["bbox"])

                for b in range(len(itemInsideList)):
                    if "isBold" not in itemInsideList[b] or itemInsideList[b]["isBold"] == None:
                        continue

                    if cellList[a]["rowIndex"] == 0:
                        countHeader += 1
                        countHeaderBold += 1 if itemInsideList[b]["isBold"] else 0
                    else:
                        countBody += 1
                        countBodyBold += 1 if itemInsideList[b]["isBold"] else 0

            return countHeader > 0 and countBody > 0 and countHeaderBold == countHeader and countBodyBold * 2 < countBody

        def _tableGridBuild(self, tableObject, directionObject):
            gridList = self.markdown._gridCellBuild(tableObject["cellList"])

            directionPageObject = directionObject[tableObject["page"]]

            if directionPageObject["isVertical"] or directionPageObject["isRightToLeft"]:
                for a in range(len(gridList)):
                    gridList[a].reverse()

            return gridList

        def _gridWrite(self, gridList, isHeader=False):
            return self.markdown._gridHeaderWrite(gridList, isHeader)

        def _itemInsideCollect(self, itemList, numberPage, bboxList):
            resultList = []

            for a in range(len(itemList)):
                if itemList[a]["page"] != numberPage:
                    continue

                if boxCenterInsideCheck(itemList[a]["bbox"], bboxList) == False:
                    continue

                resultList.append(itemList[a])

            return resultList

        def _textBuild(self, itemList, numberPage, bboxList, directionObject, isBlock):
            return self._lineListWrite(self._lineGroup(self._itemInsideCollect(itemList, numberPage, bboxList), directionObject), directionObject, isBlock)

        def _lineStart(self, lineObject, directionObject):
            directionPageObject = directionObject[lineObject["page"]]

            columnList = self._axisRange(lineObject["bbox"], directionPageObject["isVertical"] == False)

            if directionPageObject["isRightToLeft"]:
                return -columnList[1]

            return columnList[0]

        def _lineSize(self, lineObject, directionObject):
            crossList = self._axisRange(lineObject["bbox"], directionObject[lineObject["page"]]["isVertical"])

            return crossList[1] - crossList[0]

        def _lineStartDominant(self, lineList, directionObject):
            result = None

            countBest = 1

            for a in range(len(lineList)):
                start = self._lineStart(lineList[a], directionObject)

                margin = self._lineSize(lineList[a], directionObject) * self.levelLineOutdent

                count = 0

                for b in range(len(lineList)):
                    if abs(self._lineStart(lineList[b], directionObject) - start) <= margin:
                        count += 1

                if count > countBest or (count == countBest and result != None and start > result):
                    result = start

                    countBest = count

            return result

        def _lineOutdentCheck(self, startDominant, lineObject, directionObject):
            if startDominant == None:
                return False

            size = self._lineSize(lineObject, directionObject)

            distance = startDominant - self._lineStart(lineObject, directionObject)

            return distance > size * self.levelLineOutdent and distance <= size * self.levelLineOutdentMaximum

        def _listOrderFind(self, text):
            index = 0

            while index < len(text) and icu.Char.isdigit(text[index]):
                index += 1

            if index == 0 or index + 1 >= len(text) or icu.Char.ispunct(text[index]) == False or whitespaceCheck(text[index + 1]) == False:
                return {"number": -1, "mark": ""}

            return {"number": int(text[0:index]), "mark": text[index]}

        def _lineGridBuild(self, lineList, directionObject):
            resultList = []

            if len(lineList) < self.countPairLine or directionObject[lineList[0]["page"]]["isVertical"] or directionObject[lineList[0]["page"]]["isRightToLeft"]:
                return resultList

            itemFirstList = sorted(lineList[0]["itemList"], key=lambda itemObject: itemObject["bbox"][0])

            wideList = [True]

            for a in range(1, len(itemFirstList)):
                wideList.append(False)

            for a in range(len(lineList)):
                itemSortedList = sorted(lineList[a]["itemList"], key=lambda itemObject: itemObject["bbox"][0])

                if len(itemSortedList) < 2 or len(itemSortedList) != len(itemFirstList):
                    return []

                rowList = []

                for b in range(len(itemSortedList)):
                    bboxList = itemSortedList[b]["bbox"]

                    height = bboxList[3] - bboxList[1]

                    if abs(bboxList[0] - itemFirstList[b]["bbox"][0]) > height * self.levelPairAlign:
                        return []

                    if b > 0 and bboxList[0] <= itemSortedList[b - 1]["bbox"][2]:
                        return []

                    if b > 0 and bboxList[0] - itemSortedList[b - 1]["bbox"][2] >= height * self.levelColumnGap:
                        wideList[b] = True

                    rowList.append(self.markdown._cellEscape(itemSortedList[b]["text"]))

                resultList.append(rowList)

            if False in wideList:
                return []

            return resultList

        def _lineBoldSizeFind(self, lineObject):
            itemList = lineObject["itemList"]

            for a in range(len(itemList)):
                if "fontSize" not in itemList[a] or itemList[a]["isBold"] != True or itemList[a]["fontSize"] != itemList[0]["fontSize"]:
                    return 0

            return itemList[0]["fontSize"]

        def _lineTitleFind(self, lineList, index, directionObject):
            directionPageObject = directionObject[lineList[index]["page"]]

            itemSortedList = sorted(lineList[index]["itemList"], key=lambda itemObject: itemObject["bbox"][0])

            if directionPageObject["isVertical"] or directionPageObject["isRightToLeft"]:
                return None

            itemAside = None

            if len(itemSortedList) > 1:
                width = 0

                for a in range(len(itemSortedList)):
                    width += itemSortedList[a]["bbox"][2] - itemSortedList[a]["bbox"][0]

                if itemSortedList[len(itemSortedList) - 1]["bbox"][0] - itemSortedList[len(itemSortedList) - 2]["bbox"][2] > width:
                    itemAside = itemSortedList[len(itemSortedList) - 1]

                    itemSortedList = itemSortedList[0:len(itemSortedList) - 1]

            size = self._lineBoldSizeFind({"itemList": itemSortedList})

            bboxList = itemSortedList[0]["bbox"]

            if size == 0 or size not in directionPageObject["titleSizeList"] or abs(bboxList[0] - directionPageObject["marginStart"]) > (bboxList[3] - bboxList[1]) * self.levelPairAlign:
                return None

            if (index > 0 and self._lineBoldSizeFind(lineList[index - 1]) == size) or (index + 1 < len(lineList) and self._lineBoldSizeFind(lineList[index + 1]) == size):
                return None

            if index + 1 < len(lineList) and len(lineList) >= self.countParagraphLine and self._lineFillCheck(lineList, directionObject):
                edgeEnd = 0

                for a in range(len(lineList)):
                    edgeEnd = max(edgeEnd, lineList[a]["bbox"][2])

                bboxNextList = lineList[index + 1]["bbox"]

                textNext = self._lineText(lineList[index + 1], directionObject)

                if edgeEnd - itemSortedList[len(itemSortedList) - 1]["bbox"][2] <= (bboxNextList[2] - bboxNextList[0]) * tokenFirstLength(textNext) / len(textNext) + (bboxNextList[3] - bboxNextList[1]) * self.levelLineBreakSpace:
                    return None

            textTitle = self.markdown._textEscape(self.markdown.separatorText.join(self.markdown.separatorText.join([itemObject["text"] for itemObject in itemSortedList]).split()))

            if len(textTitle) > levelTitleLength or sentenceEndCheck(textTitle) or self._listMarkCheck(textTitle):
                return None

            return {"text": f"{self.labelPrefixObject['paragraph_title']}{textTitle}", "aside": self.markdown._textEscape(itemAside["text"]) if itemAside != None else ""}

        def _lineColumnSplit(self, lineList, directionObject):
            if len(lineList) < 2 or directionObject[lineList[0]["page"]]["isVertical"] or directionObject[lineList[0]["page"]]["isRightToLeft"]:
                return []

            itemSortedList = sorted(self._lineItemList(lineList), key=lambda itemObject: itemObject["bbox"][0])

            columnList = [[itemSortedList[0]]]

            edgeEnd = itemSortedList[0]["bbox"][2]

            for a in range(1, len(itemSortedList)):
                bboxList = itemSortedList[a]["bbox"]

                if bboxList[0] - edgeEnd >= (bboxList[3] - bboxList[1]) * self.levelColumnGap:
                    columnList.append([])

                columnList[len(columnList) - 1].append(itemSortedList[a])

                edgeEnd = max(edgeEnd, bboxList[2])

            resultList = []

            isColumn = False

            for a in range(len(columnList)):
                resultList.append(self._lineGroup(columnList[a], directionObject))

                bboxList = resultList[a][0]["bbox"]

                if (bboxList[1] + bboxList[3]) / 2 < resultList[0][0]["bbox"][1]:
                    isColumn = True

            if isColumn == False:
                return []

            return resultList

        def _lineListWrite(self, lineList, directionObject, isBlock):
            gridList = self._lineGridBuild(lineList, directionObject) if isBlock else []

            if len(gridList) > 0:
                return self._gridWrite(gridList)

            columnList = self._lineColumnSplit(lineList, directionObject) if isBlock else []

            if len(columnList) > 0:
                return self.markdown.separatorBlock.join([self._lineListWrite(columnList[a], directionObject, True) for a in range(len(columnList))])

            partList = []

            result = ""

            isColumnGap = len(lineList) < self.countParagraphLine or self._lineFillCheck(lineList, directionObject) == False

            startDominant = self._lineStartDominant(lineList, directionObject)

            numberOrder = -1
            markOrder = ""

            for a in range(len(lineList)):
                titleObject = self._lineTitleFind(lineList, a, directionObject) if isBlock else None

                if titleObject != None:
                    if result != "":
                        partList.append(result)

                    partList.append(titleObject["text"])

                    if titleObject["aside"] != "":
                        partList.append(titleObject["aside"])

                    result = ""

                    continue

                text = self._lineText(lineList[a], directionObject, isColumnGap)

                orderObject = self._listOrderFind(text)

                isOrder = numberOrder >= 0 and orderObject["number"] == numberOrder + 1 and orderObject["mark"] == markOrder

                if orderObject["number"] >= 0 and (a == 0 or isOrder):
                    numberOrder = orderObject["number"]
                    markOrder = orderObject["mark"]

                if result != "" and a > 0 and (isOrder or self._listMarkCheck(text) or self._lineFieldCheck(lineList[a - 1], directionObject) or self._lineBreakCheck(directionObject, lineList, a, text) or self._lineOutdentCheck(startDominant, lineList[a], directionObject)):
                    result += f"{self.markdown.separatorLine}{text}"
                else:
                    result = self.markdown._textJoin([result, text])

            if result != "":
                partList.append(result)

            return self.markdown.separatorBlock.join(partList)

        def _lineFieldCheck(self, lineObject, directionObject):
            directionPageObject = directionObject[lineObject["page"]]

            itemSortedList = sorted(lineObject["itemList"], key=lambda itemObject: self._itemOrderKey(itemObject["bbox"], directionPageObject))

            return "isField" in itemSortedList[len(itemSortedList) - 1]

        def _lineBreakCheck(self, directionObject, lineList, index, text):
            directionPageObject = directionObject[lineList[index]["page"]]

            columnList = self._axisRange(lineList[index]["bbox"], directionPageObject["isVertical"] == False)
            columnPreviousList = self._axisRange(lineList[index - 1]["bbox"], directionPageObject["isVertical"] == False)

            edgeStart = columnList[0]
            edgeEnd = columnList[1]

            for a in range(len(lineList)):
                columnOtherList = self._axisRange(lineList[a]["bbox"], directionPageObject["isVertical"] == False)

                edgeStart = min(edgeStart, columnOtherList[0])
                edgeEnd = max(edgeEnd, columnOtherList[1])

            available = columnPreviousList[0] - edgeStart if directionPageObject["isRightToLeft"] else edgeEnd - columnPreviousList[1]

            crossList = self._axisRange(lineList[index]["bbox"], directionPageObject["isVertical"])

            widthToken = (columnList[1] - columnList[0]) * tokenFirstLength(text) / len(text)

            return available > widthToken + (crossList[1] - crossList[0]) * self.levelLineBreakSpace

        def _pairLayoutBuild(self, layoutList, directionObject, itemList):
            resultObject = {"blockObject": {}, "skipList": []}

            pairSingleList = []

            for a in range(len(layoutList)):
                if self._pairCandidateCheck(directionObject, layoutList[a]) == False or a in resultObject["skipList"]:
                    continue

                indexPair = self._pairFind(directionObject, layoutList, a)

                if indexPair < 0 or indexPair in resultObject["skipList"]:
                    continue

                if layoutList[a]["flow"] == "secondary" and layoutList[indexPair]["flow"] == "secondary":
                    continue

                lineList = self._lineGroup(self._itemInsideCollect(itemList, layoutList[a]["page"], layoutList[a]["bbox"]), directionObject)
                lineOtherList = self._lineGroup(self._itemInsideCollect(itemList, layoutList[indexPair]["page"], layoutList[indexPair]["bbox"]), directionObject)

                if len(lineList) == 0 or len(lineOtherList) == 0:
                    continue

                text = ""

                if self._lineWidthCheck(lineList, directionObject, self.levelPairWidth) and self._lineWidthCheck(lineOtherList, directionObject, self.levelPairWidth):
                    text = self._pairWrite(lineList, lineOtherList, directionObject, self._sizeDominant(itemList))

                if len(text) > 0:
                    self._pairAssign(a, indexPair, layoutList, text, resultObject)

                    continue

                if len(lineList) > self.countPairLine or len(lineOtherList) > self.countPairLine:
                    continue

                if self._lineWidthCheck(lineList, directionObject, self.levelPairWidthRow) == False or self._lineWidthCheck(lineOtherList, directionObject, self.levelPairWidthRow) == False:
                    continue

                if self._pairMatch(lineList[0:1], directionObject, lineOtherList[0:1])[0] == 0:
                    pairSingleList.append({"index": a, "indexPair": indexPair, "lineList": lineList, "lineOtherList": lineOtherList})

            self._pairSingleAssign(pairSingleList, layoutList, directionObject, resultObject)

            return resultObject

        def _pairCandidateCheck(self, directionObject, layoutObject):
            if directionObject[layoutObject["page"]]["isVertical"]:
                return False

            return layoutObject["label"] in self.labelPairList

        def _pairFind(self, directionObject, layoutList, index):
            directionPageObject = directionObject[layoutList[index]["page"]]

            bboxList = layoutList[index]["bbox"]

            indexBest = -1
            keyBest = None

            for a in range(len(layoutList)):
                if a == index or layoutList[a]["page"] != layoutList[index]["page"] or self._pairCandidateCheck(directionObject, layoutList[a]) == False:
                    continue

                bboxOtherList = layoutList[a]["bbox"]

                if min(bboxList[3], bboxOtherList[3]) <= max(bboxList[1], bboxOtherList[1]):
                    continue

                distance = bboxList[0] - bboxOtherList[2] if directionPageObject["isRightToLeft"] else bboxOtherList[0] - bboxList[2]

                if distance < 0:
                    continue

                key = (abs(bboxOtherList[1] - bboxList[1]), distance)

                if indexBest < 0 or key < keyBest:
                    indexBest = a
                    keyBest = key

            return indexBest

        def _pairWrite(self, lineList, lineOtherList, directionObject, sizeBody):
            matchList = self._pairMatch(lineList, directionObject, lineOtherList)

            count = 0
            indexFirst = -1
            indexLast = -1

            for a in range(len(matchList)):
                if matchList[a] >= 0:
                    count += 1

                    indexLast = a

                    if indexFirst < 0:
                        indexFirst = a

            if count < self.countPairRow or matchList[indexFirst] > 0:
                return ""

            if count != indexLast - indexFirst + 1 or count < len(lineList) * self.levelPairMatch or count < len(lineOtherList) * self.levelPairMatch:
                return ""

            if self._lineFillCheck(lineList, directionObject) and self._lineFillCheck(lineOtherList, directionObject):
                return ""

            return self._pairTextBuild(lineList, directionObject, matchList, lineOtherList, sizeBody)

        def _lineWidthCheck(self, lineList, directionObject, level):
            total = 0

            for a in range(len(lineList)):
                directionPageObject = directionObject[lineList[a]["page"]]

                columnList = self._axisRange(lineList[a]["bbox"], directionPageObject["isVertical"] == False)
                crossList = self._axisRange(lineList[a]["bbox"], directionPageObject["isVertical"])

                total += (columnList[1] - columnList[0]) / max(1, crossList[1] - crossList[0])

            return total / len(lineList) < level

        def _pairAssign(self, index, indexPair, layoutList, text, resultObject):
            indexFirst = min(index, indexPair)
            indexLast = max(index, indexPair)

            flow = "main" if layoutList[index]["flow"] == "main" or layoutList[indexPair]["flow"] == "main" else "secondary"

            resultObject["blockObject"][indexFirst] = {"text": text, "flow": flow}
            resultObject["skipList"].append(indexLast)

        def _pairSingleAssign(self, pairSingleList, layoutList, directionObject, resultObject):
            pairSortedList = sorted(pairSingleList, key=lambda pairObject: (layoutList[pairObject["index"]]["page"], layoutList[pairObject["index"]]["bbox"][1]))

            groupList = []

            for a in range(len(pairSortedList)):
                layoutObject = layoutList[pairSortedList[a]["index"]]
                layoutOtherObject = layoutList[pairSortedList[a]["indexPair"]]

                tolerance = (layoutObject["bbox"][3] - layoutObject["bbox"][1]) * self.levelPairAlign

                isAdded = False

                if len(groupList) > 0:
                    groupObject = groupList[len(groupList) - 1]

                    if groupObject["page"] == layoutObject["page"] and abs(groupObject["x1"] - layoutObject["bbox"][0]) <= tolerance and abs(groupObject["x1Other"] - layoutOtherObject["bbox"][0]) <= tolerance:
                        groupObject["pairList"].append(pairSortedList[a])

                        isAdded = True

                if isAdded == False:
                    groupList.append({"page": layoutObject["page"], "x1": layoutObject["bbox"][0], "x1Other": layoutOtherObject["bbox"][0], "pairList": [pairSortedList[a]]})

            for a in range(len(groupList)):
                if len(groupList[a]["pairList"]) < self.countPairRow:
                    continue

                rowList = []
                indexList = []

                for b in range(len(groupList[a]["pairList"])):
                    pairObject = groupList[a]["pairList"][b]

                    rowList.append([self.markdown._cellEscape(self._lineListWrite(pairObject["lineList"], directionObject, False)), self.markdown._cellEscape(self._lineListWrite(pairObject["lineOtherList"], directionObject, False))])

                    indexList.append(pairObject["index"])
                    indexList.append(pairObject["indexPair"])

                indexFirst = min(indexList)

                flow = "secondary"

                for b in range(len(indexList)):
                    if layoutList[indexList[b]]["flow"] == "main":
                        flow = "main"

                    if indexList[b] != indexFirst:
                        resultObject["skipList"].append(indexList[b])

                resultObject["blockObject"][indexFirst] = {"text": self._gridWrite(rowList), "flow": flow}

        def _pairMatch(self, lineList, directionObject, lineOtherList):
            resultList = []

            for a in range(len(lineList)):
                directionPageObject = directionObject[lineList[a]["page"]]

                crossList = self._axisRange(lineList[a]["bbox"], directionPageObject["isVertical"])

                indexMatch = -1

                for b in range(len(lineOtherList)):
                    crossOtherList = self._axisRange(lineOtherList[b]["bbox"], directionPageObject["isVertical"])

                    if rangeOverlapRatio(crossList[0], crossList[1], crossOtherList[0], crossOtherList[1]) >= self.levelLineOverlap:
                        indexMatch = b

                        break

                resultList.append(indexMatch)

            return resultList

        def _lineFillCheck(self, lineList, directionObject):
            edgeStart = -1
            edgeEnd = -1

            for a in range(len(lineList)):
                columnList = self._axisRange(lineList[a]["bbox"], directionObject[lineList[a]["page"]]["isVertical"] == False)

                edgeStart = columnList[0] if a == 0 else min(edgeStart, columnList[0])
                edgeEnd = columnList[1] if a == 0 else max(edgeEnd, columnList[1])

            count = 0

            for a in range(len(lineList)):
                columnList = self._axisRange(lineList[a]["bbox"], directionObject[lineList[a]["page"]]["isVertical"] == False)

                if columnList[1] - columnList[0] >= (edgeEnd - edgeStart) * self.levelPairFill:
                    count += 1

            return count > len(lineList) * self.levelPairFillCount

        def _pairTextBuild(self, lineList, directionObject, matchList, lineOtherList, sizeBody):
            blockTextList = []
            rowList = []

            for a in range(len(lineList)):
                text = self._lineText(lineList[a], directionObject)

                if matchList[a] < 0:
                    if len(rowList) > 0:
                        blockTextList.append(self._gridWrite(rowList))

                        rowList = []

                    blockTextList.append(self._lineTitleWrite(lineList[a], directionObject, sizeBody))

                    continue

                indexNext = len(lineOtherList)

                for b in range(a + 1, len(lineList)):
                    if matchList[b] >= 0:
                        indexNext = matchList[b]

                        break

                textOtherList = []

                for b in range(matchList[a], indexNext):
                    textOtherList.append(self._lineText(lineOtherList[b], directionObject))

                rowList.append([self.markdown._cellEscape(text), self.markdown._cellEscape(self.markdown._textJoin(textOtherList))])

            if len(rowList) > 0:
                blockTextList.append(self._gridWrite(rowList))

            return self.markdown.separatorBlock.join(blockTextList)

        def _furnitureKey(self, text):
            textNormalized = textNormalize(text)

            result = ""

            for a in range(len(textNormalized)):
                if icu.Char.isdigit(textNormalized[a]) == False:
                    result += textNormalized[a]

            return result if len(result) > 0 else textNormalized

        def _furnitureSplit(self, blockList):
            pageObject = {}

            for a in range(len(blockList)):
                if blockList[a]["page"] not in pageObject:
                    pageObject[blockList[a]["page"]] = []

                pageObject[blockList[a]["page"]].append(a)

            textPageObject = {}

            for numberPage in pageObject:
                indexList = pageObject[numberPage]

                for b in range(len(indexList)):
                    block = blockList[indexList[b]]

                    if block["tableObject"] != None or block["label"] == "pair":
                        continue

                    if b >= self.countFurniture and b < len(indexList) - self.countFurniture:
                        continue

                    key = self._furnitureKey(block["text"])

                    if key not in textPageObject:
                        textPageObject[key] = []

                    if numberPage not in textPageObject[key]:
                        textPageObject[key].append(numberPage)

            resultObject = {"blockList": [], "textList": []}

            textWrittenList = []

            for a in range(len(blockList)):
                key = self._furnitureKey(blockList[a]["text"])

                if key not in textPageObject or len(textPageObject[key]) < self.countFurniturePage:
                    resultObject["blockList"].append(blockList[a])

                    continue

                if key not in textWrittenList:
                    textWrittenList.append(key)

                    resultObject["textList"].append(blockList[a]["text"])

            return resultObject

        def _blockJoinable(self, layoutObject):
            label = layoutObject["label"]

            if label in self.labelPlaceholderList or label in self.labelBarrierList:
                return False

            return label not in self.labelPrefixObject

        def _blockMerge(self, blockList, directionObject):
            resultList = []

            for a in range(len(blockList)):
                if blockList[a]["tableObject"] != None:
                    indexTable = self._tablePreviousFind(resultList, blockList[a], False)

                    if indexTable >= 0 and self._tableMerge(directionObject, blockList[a], resultList[indexTable], False):
                        continue

                    if indexTable < 0:
                        indexTable = self._tablePreviousFind(resultList, blockList[a], True)

                        if indexTable >= 0 and self._tableMerge(directionObject, blockList[a], resultList[indexTable], True):
                            continue

                if len(resultList) > 0:
                    blockPrevious = resultList[len(resultList) - 1]

                    if blockPrevious["isJoinable"] and blockList[a]["isJoinable"] and self._pageBreakCheck(blockPrevious, blockList[a], directionObject) and sentenceEndCheck(blockPrevious["text"]) == False:
                        blockPrevious["text"] = self.markdown._textJoin([blockPrevious["text"], blockList[a]["text"]])
                        blockPrevious["page"] = blockList[a]["page"]
                        blockPrevious["bbox"] = blockList[a]["bbox"]

                        continue

                resultList.append(blockList[a])

            textList = []

            for a in range(len(resultList)):
                textList.append(resultList[a]["text"])

            return textList

        def _tablePreviousFind(self, resultList, blockObject, isTextSkip):
            countSkip = 0

            for a in range(len(resultList) - 1, -1, -1):
                if resultList[a]["page"] < blockObject["page"] - 1:
                    return -1

                if resultList[a]["label"] in self.labelPageList:
                    continue

                if resultList[a]["page"] == blockObject["page"]:
                    return -1

                if resultList[a]["tableObject"] != None:
                    return a

                countSkip += 1

                if isTextSkip == False or countSkip > self.countFurniture:
                    return -1

            return -1

        def _tableMerge(self, directionObject, blockObject, blockPrevious, isFragmentRequired):
            if directionObject[blockObject["page"]]["isVertical"]:
                return False

            columnPreviousList = blockPrevious["columnList"] if "columnList" in blockPrevious else self._columnBuild(blockPrevious["tableObject"], directionObject)
            columnList = self._columnBuild(blockObject["tableObject"], directionObject)

            mapList = self._columnMap(columnList, columnPreviousList)

            if len(mapList) == 0:
                return False

            gridPreviousList = blockPrevious["gridList"] if "gridList" in blockPrevious else self._tableGridBuild(blockPrevious["tableObject"], directionObject)

            gridList = self._tableGridBuild(blockObject["tableObject"], directionObject)

            rowMappedList = self._gridMap(gridList, len(columnPreviousList), mapList)

            isColumnDifferent = len(columnList) != len(columnPreviousList)

            if isColumnDifferent:
                rowMappedList = self._gridFragmentJoin(rowMappedList)

                if len(rowMappedList) != 1:
                    return False

            tableLastObject = blockPrevious["tableLastObject"] if "tableLastObject" in blockPrevious else blockPrevious["tableObject"]

            indexStart = 0

            while indexStart < len(rowMappedList) and indexStart < len(gridPreviousList) and rowMappedList[indexStart] == gridPreviousList[indexStart]:
                indexStart += 1

            if indexStart > 0:
                blockPrevious["isHeader"] = True

            isFragment = indexStart < len(rowMappedList) and self._rowFragmentCheck(rowMappedList[indexStart], gridPreviousList[len(gridPreviousList) - 1], tableLastObject)

            if isFragmentRequired and isFragment == False and isColumnDifferent == False:
                return False

            if isFragment:
                for b in range(len(columnPreviousList)):
                    if rowMappedList[indexStart][b] != self.markdown.textCellEmpty:
                        gridPreviousList[len(gridPreviousList) - 1][b] = self.markdown._textJoin([gridPreviousList[len(gridPreviousList) - 1][b], rowMappedList[indexStart][b]])

                indexStart += 1

            blockPrevious["gridList"] = gridPreviousList + rowMappedList[indexStart:]
            blockPrevious["columnList"] = columnPreviousList
            blockPrevious["tableLastObject"] = blockObject["tableObject"]
            blockPrevious["text"] = self._gridWrite(blockPrevious["gridList"], blockPrevious["isHeader"])
            blockPrevious["page"] = blockObject["page"]
            blockPrevious["bbox"] = blockObject["bbox"]

            return True

        def _columnBuild(self, tableObject, directionObject):
            cellList = tableObject["cellList"]

            resultObject = {}

            for a in range(len(cellList)):
                if cellList[a]["columnSpan"] > 1:
                    continue

                columnIndex = cellList[a]["columnIndex"]

                bboxList = cellList[a]["bbox"]

                if columnIndex not in resultObject:
                    resultObject[columnIndex] = [bboxList[0], bboxList[2]]

                    continue

                resultObject[columnIndex][0] = min(resultObject[columnIndex][0], bboxList[0])
                resultObject[columnIndex][1] = max(resultObject[columnIndex][1], bboxList[2])

            resultList = []

            for columnIndex in sorted(resultObject):
                resultList.append(resultObject[columnIndex])

            if directionObject[tableObject["page"]]["isRightToLeft"]:
                resultList.reverse()

            return resultList

        def _columnMap(self, columnList, columnPreviousList):
            resultList = []

            for a in range(len(columnList)):
                indexBest = -1
                overlapBest = 0

                for b in range(len(columnPreviousList)):
                    overlap = rangeOverlapRatio(columnList[a][0], columnList[a][1], columnPreviousList[b][0], columnPreviousList[b][1])

                    if overlap > overlapBest:
                        indexBest = b
                        overlapBest = overlap

                if overlapBest < levelColumnOverlap or indexBest in resultList:
                    return []

                resultList.append(indexBest)

            return resultList

        def _gridMap(self, gridList, countColumn, mapList):
            resultList = []

            for a in range(len(gridList)):
                rowList = []

                for b in range(countColumn):
                    rowList.append(self.markdown.textCellEmpty)

                for b in range(min(len(gridList[a]), len(mapList))):
                    rowList[mapList[b]] = gridList[a][b]

                resultList.append(rowList)

            return resultList

        def _gridFragmentJoin(self, gridList):
            resultList = []

            for a in range(len(gridList)):
                if len(resultList) > 0 and self._rowFragmentCheck(gridList[a], resultList[len(resultList) - 1], None):
                    for b in range(len(gridList[a])):
                        if gridList[a][b] != self.markdown.textCellEmpty:
                            resultList[len(resultList) - 1][b] = self.markdown._textJoin([resultList[len(resultList) - 1][b], gridList[a][b]])

                    continue

                resultList.append(gridList[a])

            return resultList

        def _rowFragmentCheck(self, rowList, rowPreviousList, tableObject):
            count = 0
            countPrevious = 0

            for a in range(len(rowList)):
                if rowPreviousList[a] != self.markdown.textCellEmpty:
                    countPrevious += 1

                if rowList[a] == self.markdown.textCellEmpty:
                    continue

                if rowPreviousList[a] == self.markdown.textCellEmpty:
                    return False

                count += 1

            if count == 0 or len(rowList) < 2:
                return False

            return count == 1 or (tableObject != None and count < countPrevious and self._rowTruncatedCheck(tableObject))

        def _rowTruncatedCheck(self, tableObject):
            cellList = tableObject["cellList"]

            heightObject = {}

            for a in range(len(cellList)):
                if cellList[a]["rowSpan"] > 1:
                    continue

                heightObject[cellList[a]["rowIndex"]] = cellList[a]["bbox"][3] - cellList[a]["bbox"][1]

            rowIndexList = sorted(heightObject)

            if len(rowIndexList) < 2:
                return False

            heightList = []

            for a in range(len(rowIndexList) - 1):
                heightList.append(heightObject[rowIndexList[a]])

            heightList.sort()

            return heightObject[rowIndexList[len(rowIndexList) - 1]] < heightList[len(heightList) // 2] * self.levelRowTruncated

        def _pageBreakCheck(self, blockPrevious, blockObject, directionObject):
            if blockPrevious["page"] + 1 != blockObject["page"]:
                return False

            columnPreviousList = self._axisRange(blockPrevious["bbox"], directionObject[blockPrevious["page"]]["isVertical"] == False)
            columnList = self._axisRange(blockObject["bbox"], directionObject[blockObject["page"]]["isVertical"] == False)

            return rangeOverlapRatio(columnPreviousList[0], columnPreviousList[1], columnList[0], columnList[1]) >= levelColumnOverlap

        def _orphanAppend(self, lineObject, layoutList, directionObject, blockList, secondaryList, sizeBody):
            if self._lineFlow(lineObject, layoutList, directionObject) == "main":
                blockList.append({"text": self._lineTitleWrite(lineObject, directionObject, sizeBody), "isJoinable": False, "page": lineObject["page"], "bbox": None, "label": "text", "tableObject": None})

                return

            secondaryList.append(self._lineText(lineObject, directionObject))

        def _tableRowLineList(self, tableObject, rowStart, rowEnd, itemList, directionObject):
            resultList = []

            cellList = tableObject["cellList"]

            for a in range(len(cellList)):
                if cellList[a]["rowIndex"] < rowStart or cellList[a]["rowIndex"] >= rowEnd:
                    continue

                resultList = resultList + self._lineGroup(self._itemInsideCollect(itemList, tableObject["page"], cellList[a]["bbox"]), directionObject)

            return resultList

        def _lineItemList(self, lineList):
            resultList = []

            for a in range(len(lineList)):
                resultList = resultList + lineList[a]["itemList"]

            return resultList

        def _tableEdgeMissingCheck(self, lineList, directionPageObject, lineOtherList, margin):
            for a in range(len(lineList)):
                columnList = self._axisRange(lineList[a]["bbox"], directionPageObject["isVertical"] == False)

                isFound = False

                for b in range(len(lineOtherList)):
                    columnOtherList = self._axisRange(lineOtherList[b]["bbox"], directionPageObject["isVertical"] == False)

                    if abs(columnOtherList[0] - columnList[0]) <= margin or abs(columnOtherList[1] - columnList[1]) <= margin or abs(columnOtherList[0] + columnOtherList[1] - columnList[0] - columnList[1]) <= margin * 2:
                        isFound = True

                        break

                if isFound == False:
                    return True

            return False

        def _tableTitleFind(self, tableObject, rowIndex, itemList, directionObject, rowStart, countRow):
            cellList = tableObject["cellList"]

            cellTitle = None

            for a in range(len(cellList)):
                if cellList[a]["rowIndex"] < rowIndex and cellList[a]["rowIndex"] + cellList[a]["rowSpan"] > rowIndex:
                    return None

                if cellList[a]["rowIndex"] != rowIndex or len(cellList[a]["text"].strip()) == 0:
                    continue

                if cellTitle != None:
                    return None

                cellTitle = cellList[a]

            if cellTitle == None:
                return None

            itemTitleList = self._itemInsideCollect(itemList, tableObject["page"], cellTitle["bbox"])

            lineTitleList = self._lineGroup(itemTitleList, directionObject)

            lineBeforeList = self._tableRowLineList(tableObject, rowStart, rowIndex, itemList, directionObject)
            lineAfterList = self._tableRowLineList(tableObject, rowIndex + 1, countRow, itemList, directionObject)

            size = self._sizeDominant(itemTitleList)
            sizeTable = self._sizeDominant(self._lineItemList(lineBeforeList + lineAfterList))

            if len(lineTitleList) == 0 or size == 0 or sizeTable == 0 or len(lineBeforeList) == 0 or len(lineAfterList) == 0:
                return None

            text = self._lineText(lineTitleList[0], directionObject)

            if self._listMarkCheck(text) or self._titleCheck(lineTitleList, directionObject, size, sizeTable) == False:
                return None

            directionPageObject = directionObject[tableObject["page"]]

            crossList = self._axisRange(lineTitleList[0]["bbox"], directionPageObject["isVertical"])

            margin = (crossList[1] - crossList[0]) * self.levelTableTitleAlign

            if self._tableEdgeMissingCheck(lineAfterList, directionPageObject, lineBeforeList, margin) == False and self._tableEdgeMissingCheck(lineBeforeList, directionPageObject, lineAfterList, margin) == False:
                return None

            return {"text": f"{self.labelPrefixObject['paragraph_title']}{text}", "isJoinable": False, "page": tableObject["page"], "bbox": cellTitle["bbox"], "label": "paragraph_title", "tableObject": None}

        def _tableRowSlice(self, tableObject, rowStart, rowEnd, itemList, directionObject):
            cellList = []

            bboxList = None

            for a in range(len(tableObject["cellList"])):
                cellObject = dict(tableObject["cellList"][a])

                if cellObject["rowIndex"] < rowStart or cellObject["rowIndex"] >= rowEnd:
                    continue

                cellObject["rowIndex"] -= rowStart

                cellList.append(cellObject)

                bboxList = list(cellObject["bbox"]) if bboxList == None else boxExpand(bboxList, cellObject["bbox"])

            sliceObject = dict(tableObject)

            sliceObject["cellList"] = cellList
            sliceObject["bbox"] = bboxList

            return {"text": self._tableObjectWrite(sliceObject, itemList, directionObject), "isJoinable": False, "page": sliceObject["page"], "bbox": bboxList, "label": "table", "tableObject": sliceObject, "isHeader": self._rowBoldCheck(sliceObject, itemList)}

        def _optionFind(self, text, position):
            result = -1

            for a in range(len(self.markdown.textOptionList)):
                index = text.find(self.markdown.textOptionList[a], position)

                if index >= 0 and (result < 0 or index < result):
                    result = index

            return result

        def _optionTextSplit(self, text):
            positionList = []

            position = self._optionFind(text, 0)

            while position >= 0:
                positionList.append(position)

                position = self._optionFind(text, position + 1)

            if len(positionList) == 0:
                return {"key": text, "value": ""}

            partList = []

            for a in range(len(positionList)):
                partList.append(text[positionList[a]:positionList[a + 1] if a + 1 < len(positionList) else len(text)].strip())

            return {"key": text[0:positionList[0]].strip(), "value": separatorOption.join(partList)}

        def _lineStyleCheck(self, lineObject, lineOtherObject):
            size = self._sizeDominant(lineObject["itemList"])

            return size > 0 and size == self._sizeDominant(lineOtherObject["itemList"]) and self._boldCheck(lineObject["itemList"]) == self._boldCheck(lineOtherObject["itemList"])

        def _fieldAboveBuild(self, blockList, layoutList, index, tableObject, itemList, directionObject):
            if len(blockList) == 0 or index == 0:
                return None

            blockObject = blockList[len(blockList) - 1]
            layoutObject = layoutList[index - 1]

            if blockObject["label"] != "text" or blockObject["page"] != tableObject["page"] or layoutObject["page"] != tableObject["page"] or blockObject["bbox"] != layoutObject["bbox"]:
                return None

            lineList = self._lineGroup(self._itemInsideCollect(itemList, tableObject["page"], layoutObject["bbox"]), directionObject)

            cellList = sorted(tableObject["cellList"], key=lambda cellObject: (cellObject["rowIndex"], cellObject["columnIndex"]))

            lineKeyList = []

            for a in range(len(cellList)):
                if len(lineKeyList) == 0:
                    lineKeyList = self._lineGroup(self._itemInsideCollect(itemList, tableObject["page"], cellList[a]["bbox"]), directionObject)

            if len(lineList) == 0 or len(lineKeyList) == 0:
                return None

            bboxFirstList = lineList[0]["bbox"]
            bboxLastList = lineList[len(lineList) - 1]["bbox"]
            bboxKeyList = lineKeyList[0]["bbox"]
            bboxTableList = tableObject["bbox"]

            height = bboxFirstList[3] - bboxFirstList[1]

            if self._lineStyleCheck(lineList[0], lineKeyList[0]) == False or abs(bboxFirstList[0] - bboxKeyList[0]) > height * self.levelPairAlign or bboxTableList[1] - bboxLastList[3] < height * self.levelFieldFree or layoutObject["bbox"][2] > bboxTableList[2] + height:
                return None

            resultObject = dict(tableObject)

            resultObject["cellList"] = [{"rowIndex": 0, "columnIndex": 0, "rowSpan": 1, "columnSpan": self.markdown._gridSize(cellList)["countColumn"], "bbox": [bboxTableList[0], layoutObject["bbox"][1], bboxTableList[2], bboxTableList[1]], "text": self._lineListWrite(lineList, directionObject, False)}]

            for a in range(len(cellList)):
                cellObject = dict(cellList[a])

                cellObject["rowIndex"] += 1

                resultObject["cellList"].append(cellObject)

            return resultObject

        def _fieldTableWrite(self, tableObject, itemList, directionObject):
            directionPageObject = directionObject[tableObject["page"]]

            if directionPageObject["isVertical"] or directionPageObject["isRightToLeft"]:
                return ""

            cellList = sorted(tableObject["cellList"], key=lambda cellObject: (cellObject["rowIndex"], cellObject["columnIndex"]))

            rowCellObject = {}

            for a in range(len(cellList)):
                if cellList[a]["rowIndex"] not in rowCellObject:
                    rowCellObject[cellList[a]["rowIndex"]] = []

                rowCellObject[cellList[a]["rowIndex"]].append(cellList[a])

            rowBoxList = []

            for rowIndex in rowCellObject:
                isBox = len(rowCellObject[rowIndex]) >= self.countBoxCell

                for a in range(len(rowCellObject[rowIndex])):
                    if categoryContainCheck(rowCellObject[rowIndex][a]["text"], categoryWordList):
                        isBox = False

                if isBox:
                    rowBoxList.append(rowIndex)

            rowList = []
            rowTextList = []
            lineTextList = []

            countField = 0

            isFieldPrevious = False
            isEntry = len(rowBoxList) > 0

            for a in range(len(cellList)):
                if cellList[a]["rowIndex"] in rowBoxList:
                    continue

                lineList = self._lineGroup(self._itemInsideCollect(itemList, tableObject["page"], cellList[a]["bbox"]), directionObject)

                if len(lineList) == 0:
                    continue

                bboxFirstList = lineList[0]["bbox"]
                bboxLastList = lineList[len(lineList) - 1]["bbox"]

                spaceBelow = cellList[a]["bbox"][3] - bboxLastList[3]

                isField = spaceBelow >= (bboxFirstList[3] - bboxFirstList[1]) * self.levelFieldFree and bboxFirstList[1] - cellList[a]["bbox"][1] <= spaceBelow * self.levelFieldRatio

                optionList = []

                indexOption = -1

                for b in range(len(lineList)):
                    optionList.append(self._optionTextSplit(self._lineText(lineList[b], directionObject, False)))

                    if indexOption < 0 and optionList[b]["value"] != "":
                        indexOption = b

                keyList = []
                valueList = []

                for b in range(len(lineList)):
                    if indexOption < 0:
                        if b == 0 or isField == False or self._lineStyleCheck(lineList[0], lineList[b]):
                            keyList.append(self._lineText(lineList[b], directionObject))
                        else:
                            valueList.append(self._lineText(lineList[b], directionObject))

                        continue

                    if b < indexOption:
                        keyList.append(optionList[b]["key"])

                        continue

                    if b == indexOption and optionList[b]["key"] != "":
                        keyList.append(optionList[b]["key"])
                    elif optionList[b]["value"] != "" and optionList[b]["key"] != "":
                        valueList.append(optionList[b]["key"])

                    valueList.append(optionList[b]["value"] if optionList[b]["value"] != "" else optionList[b]["key"])

                if indexOption >= 0:
                    isField = True

                countWord = 0

                for b in range(len(rowCellObject[cellList[a]["rowIndex"]])):
                    if categoryContainCheck(rowCellObject[cellList[a]["rowIndex"]][b]["text"], categoryWordList):
                        countWord += 1

                if countWord == 1:
                    if cellList[a]["rowIndex"] + cellList[a]["rowSpan"] in rowBoxList:
                        isField = True
                elif isField == False:
                    isEntry = False

                key = self.markdown._cellEscape(self.markdown._textJoin(keyList))
                value = self.markdown._cellEscape(self.markdown._textJoin(valueList))

                if key == "" and len(rowList) > 0 and rowList[len(rowList) - 1][1] == "" and isFieldPrevious == False:
                    rowList[len(rowList) - 1][1] = value

                    countField += 1
                else:
                    rowList.append([key, value])
                    rowTextList.append(isField == False)
                    lineTextList.append(self._lineListWrite(lineList, directionObject, True))

                    countField += 1 if isField else 0

                isFieldPrevious = isField

            if isEntry and countField > 0:
                return self._entryWrite(rowList, rowTextList)

            if len(rowList) < self.countFieldMinimum or countField < len(rowList) * self.levelFieldShare:
                return ""

            countTitle = 0

            while countTitle < len(rowList) and rowTextList[countTitle]:
                countTitle += 1

            blockList = lineTextList[0:countTitle]

            blockList.append(self.markdown._tableWrite(self.headerFieldList, rowList[countTitle:]))

            return self.markdown.separatorBlock.join(blockList)

        def _entryWrite(self, rowList, rowTextList):
            blockList = []

            rowFieldList = []

            for a in range(len(rowList) + 1):
                if a < len(rowList) and rowTextList[a] == False:
                    rowFieldList.append(rowList[a])

                    continue

                if len(rowFieldList) > 0:
                    blockList.append(self.markdown._tableWrite(self.headerFieldList, rowFieldList))

                    rowFieldList = []

                if a < len(rowList):
                    blockList.append(self.markdown._textJoin([rowList[a][0], rowList[a][1]]))

            return self.markdown.separatorBlock.join(blockList)

        def _tableSpanSplit(self, tableObject, itemList, directionObject):
            cellList = tableObject["cellList"]

            sizeObject = self.markdown._gridSize(cellList)

            countRow = sizeObject["countRow"]

            if sizeObject["countColumn"] < self.markdown.countHeaderColumnMinimum:
                return []

            rowCellObject = {}

            for a in range(len(cellList)):
                for b in range(cellList[a]["rowIndex"], cellList[a]["rowIndex"] + cellList[a]["rowSpan"]):
                    if b not in rowCellObject:
                        rowCellObject[b] = []

                    rowCellObject[b].append(cellList[a])

            isSpanList = []

            for a in range(countRow):
                rowList = rowCellObject[a] if a in rowCellObject else []

                isSpanList.append(len(rowList) == 1 and rowList[0]["rowSpan"] == 1 and rowList[0]["columnSpan"] >= sizeObject["countColumn"] and len(rowList[0]["text"].strip()) > 0)

            rowStart = 0

            while rowStart < countRow and isSpanList[rowStart]:
                rowStart += 1

            rowEnd = countRow

            while rowEnd > rowStart and isSpanList[rowEnd - 1]:
                rowEnd -= 1

            if rowStart == 0 and rowEnd == countRow:
                return []

            resultList = []

            rangeList = [[0, rowStart], [rowStart, rowEnd], [rowEnd, countRow]]

            for a in range(len(rangeList)):
                if rangeList[a][0] >= rangeList[a][1]:
                    continue

                if a == 1:
                    resultList.append(self._tableRowSlice(tableObject, rangeList[a][0], rangeList[a][1], itemList, directionObject))

                    continue

                bboxList = None

                for b in range(rangeList[a][0], rangeList[a][1]):
                    bboxList = list(rowCellObject[b][0]["bbox"]) if bboxList == None else boxExpand(bboxList, rowCellObject[b][0]["bbox"])

                resultList.append({"text": self._textBuild(itemList, tableObject["page"], bboxList, directionObject, True), "isJoinable": False, "page": tableObject["page"], "bbox": bboxList, "label": "text", "tableObject": None})

            return resultList

        def _tableInsideRemove(self, tableObject, tableList, itemList):
            bboxList = tableObject["bbox"]

            resultList = itemList

            for a in range(len(tableList)):
                bboxOtherList = tableList[a]["bbox"]

                if tableList[a] is tableObject or tableList[a]["page"] != tableObject["page"]:
                    continue

                area = (bboxList[2] - bboxList[0]) * (bboxList[3] - bboxList[1])
                areaOther = (bboxOtherList[2] - bboxOtherList[0]) * (bboxOtherList[3] - bboxOtherList[1])

                if areaOther >= area or boxIntersection(bboxList, bboxOtherList) < areaOther * levelColumnOverlap:
                    continue

                itemKeepList = []

                for b in range(len(resultList)):
                    if resultList[b]["page"] == tableObject["page"] and boxCenterInsideCheck(resultList[b]["bbox"], bboxOtherList):
                        continue

                    itemKeepList.append(resultList[b])

                resultList = itemKeepList

            return resultList

        def _tableCoverCheck(self, layoutObject, itemList, layoutList, tableList):
            if layoutObject["label"] == "table" or layoutObject["label"] in self.labelPlaceholderList:
                return False

            itemInsideList = self._itemInsideCollect(itemList, layoutObject["page"], layoutObject["bbox"])

            for a in range(len(layoutList)):
                if layoutList[a]["label"] != "table" or layoutList[a]["page"] != layoutObject["page"] or self._tableFind(tableList, layoutList[a]) == None:
                    continue

                if len(itemInsideList) > 0 and len(self._itemInsideCollect(itemInsideList, layoutObject["page"], layoutList[a]["bbox"])) == len(itemInsideList):
                    return True

            return False

        def _tableRowMateBuild(self, blockList, layoutObject, itemList, directionObject):
            if len(blockList) == 0 or layoutObject["label"] != "text":
                return None

            tableObject = blockList[len(blockList) - 1]["tableObject"]

            if tableObject == None or tableObject["page"] != layoutObject["page"] or self.markdown._gridSize(tableObject["cellList"])["countRow"] != 1:
                return None

            bboxList = layoutObject["bbox"]
            bboxTableList = tableObject["bbox"]

            lineList = self._lineGroup(self._itemInsideCollect(itemList, layoutObject["page"], bboxList), directionObject)

            if len(lineList) != 1 or bboxList[0] < bboxTableList[2] or (bboxList[1] + bboxList[3]) / 2 < bboxTableList[1] or (bboxList[1] + bboxList[3]) / 2 > bboxTableList[3]:
                return None

            resultObject = dict(tableObject)

            resultObject["cellList"] = list(tableObject["cellList"]) + [{"rowIndex": 0, "columnIndex": self.markdown._gridSize(tableObject["cellList"])["countColumn"], "rowSpan": 1, "columnSpan": 1, "bbox": bboxList, "text": self._lineText(lineList[0], directionObject, False)}]
            resultObject["bbox"] = boxExpand(list(bboxTableList), bboxList)

            return resultObject

        def _tableOwnRemove(self, itemList, tableObject, layoutList, tableList):
            resultList = itemList

            for a in range(len(layoutList)):
                if layoutList[a]["page"] != tableObject["page"] or layoutList[a]["label"] == "table" or layoutList[a]["label"] in self.labelPlaceholderList or self._tableCoverCheck(layoutList[a], itemList, layoutList, tableList):
                    continue

                itemKeepList = []

                for b in range(len(resultList)):
                    if resultList[b]["page"] != tableObject["page"] or boxCenterInsideCheck(resultList[b]["bbox"], layoutList[a]["bbox"]) == False:
                        itemKeepList.append(resultList[b])

                resultList = itemKeepList

            return resultList

        def _tableFieldCheck(self, tableObject, itemList):
            itemInsideList = self._itemInsideCollect(itemList, tableObject["page"], tableObject["bbox"])

            for a in range(len(itemInsideList)):
                if "isField" not in itemInsideList[a]:
                    return False

            return True

        def _tableCutCheck(self, tableObject, itemList):
            itemInsideList = self._itemInsideCollect(itemList, tableObject["page"], tableObject["bbox"])

            cellList = tableObject["cellList"]

            countCut = 0

            for a in range(len(itemInsideList)):
                bboxList = itemInsideList[a]["bbox"]

                isCut = False

                for b in range(len(cellList)):
                    if textCutCheck(bboxList, cellList[b]["bbox"]):
                        isCut = True

                if isCut:
                    countCut += 1

            return countCut > 0 and countCut >= len(itemInsideList) * self.levelTableCut

        def _tableTitleSplit(self, tableObject, itemList, directionObject):
            resultList = []

            countRow = self.markdown._gridSize(tableObject["cellList"])["countRow"]

            rowStart = 0

            for a in range(1, countRow - 1):
                if a == rowStart:
                    continue

                titleObject = self._tableTitleFind(tableObject, a, itemList, directionObject, rowStart, countRow)

                if titleObject == None:
                    continue

                resultList.append(self._tableRowSlice(tableObject, rowStart, a, itemList, directionObject))
                resultList.append(titleObject)

                rowStart = a + 1

            if len(resultList) > 0:
                resultList.append(self._tableRowSlice(tableObject, rowStart, countRow, itemList, directionObject))

            return resultList

        def execute(self, resultObject, extension):
            layoutList = resultObject["layoutList"]
            tableList = resultObject["tableList"]
            itemList = resultObject["itemList"]

            directionObject = {}

            for a in range(len(resultObject["directionList"])):
                directionObject[resultObject["directionList"][a]["page"]] = resultObject["directionList"][a]

            lineRotateList = []

            itemUprightList = []

            for a in range(len(itemList)):
                if "isRotate" in itemList[a]:
                    lineRotateList.append({"page": itemList[a]["page"], "bbox": itemList[a]["bbox"], "itemList": [itemList[a]]})
                else:
                    itemUprightList.append(itemList[a])

            itemList = itemUprightList

            self._labelRefine(layoutList, itemList, directionObject)

            layoutList = self._layoutTitleMerge(layoutList, directionObject, itemList)

            self._titleContextBuild(layoutList, itemList, directionObject)

            layoutList = self._layoutLineSplit(layoutList, directionObject, itemList)

            moduleObject = {}

            for a in range(len(resultObject["moduleList"])):
                moduleObject[resultObject["moduleList"][a]["page"]] = resultObject["moduleList"][a]["text"]

            moduleWrittenList = []

            itemFlowList = []

            for a in range(len(itemList)):
                if itemList[a]["page"] not in moduleObject:
                    itemFlowList.append(itemList[a])

            blockList = []
            secondaryList = []

            lineOrphanList = sorted(self._lineGroup(self._itemOrphanCollect(itemFlowList, layoutList), directionObject) + [lineObject for lineObject in lineRotateList if lineObject["page"] not in moduleObject], key=lambda lineObject: (lineObject["page"], self._lineFlowKey(lineObject["bbox"], directionObject[lineObject["page"]])))

            pairObject = self._pairLayoutBuild(layoutList, directionObject, itemFlowList)

            sizeBody = self._sizeDominant(itemList)

            indexOrphan = 0

            for a in range(len(layoutList)):
                flowBlock = self._lineFlowKey(layoutList[a]["bbox"], directionObject[layoutList[a]["page"]])

                while indexOrphan < len(lineOrphanList) and (lineOrphanList[indexOrphan]["page"], self._lineFlowKey(lineOrphanList[indexOrphan]["bbox"], directionObject[lineOrphanList[indexOrphan]["page"]])) < (layoutList[a]["page"], flowBlock):
                    self._orphanAppend(lineOrphanList[indexOrphan], layoutList, directionObject, blockList, secondaryList, sizeBody)

                    indexOrphan += 1

                if a in pairObject["skipList"]:
                    continue

                if a in pairObject["blockObject"]:
                    if pairObject["blockObject"][a]["flow"] == "main":
                        blockList.append({"text": pairObject["blockObject"][a]["text"], "isJoinable": False, "page": layoutList[a]["page"], "bbox": layoutList[a]["bbox"], "label": "pair", "tableObject": None})
                    else:
                        secondaryList.append(pairObject["blockObject"][a]["text"])

                    continue

                tableMateObject = None

                if layoutList[a]["page"] not in moduleObject:
                    tableMateObject = self._tableRowMateBuild(blockList, layoutList[a], itemList, directionObject)

                if tableMateObject != None:
                    blockList[len(blockList) - 1]["text"] = self._tableObjectWrite(tableMateObject, itemList, directionObject)
                    blockList[len(blockList) - 1]["bbox"] = tableMateObject["bbox"]
                    blockList[len(blockList) - 1]["tableObject"] = tableMateObject

                    continue

                if layoutList[a]["page"] in moduleObject:
                    block = self._moduleWrite(layoutList[a], moduleObject, moduleWrittenList)
                elif self._tableCoverCheck(layoutList[a], itemList, layoutList, tableList):
                    continue
                else:
                    block = self._blockWrite(layoutList[a], tableList, itemList, directionObject)

                if len(block) == 0:
                    continue

                if layoutList[a]["flow"] == "secondary":
                    secondaryList.append(block)

                    continue

                tableObject = None
                isHeader = False

                if layoutList[a]["label"] == "table" and layoutList[a]["page"] not in moduleObject:
                    tableObject = self._tableFind(tableList, layoutList[a])

                    if tableObject != None:
                        itemOutsideList = self._tableInsideRemove(tableObject, tableList, itemList)

                        if len(itemOutsideList) < len(itemList) or self._tableCutCheck(tableObject, itemList) or self._tableFieldCheck(tableObject, itemList):
                            textTable = self._textBuild(self._tableOwnRemove(itemOutsideList, tableObject, layoutList, tableList), layoutList[a]["page"], layoutList[a]["bbox"], directionObject, True)

                            if textTable != "":
                                blockList.append({"text": textTable, "isJoinable": False, "page": layoutList[a]["page"], "bbox": layoutList[a]["bbox"], "label": "text", "tableObject": None})

                            continue

                        fieldText = self._fieldTableWrite(tableObject, itemList, directionObject)

                        if fieldText != "":
                            tableAboveObject = self._fieldAboveBuild(blockList, layoutList, a, tableObject, itemList, directionObject)

                            if tableAboveObject != None:
                                blockList.pop()

                                fieldText = self._fieldTableWrite(tableAboveObject, itemList, directionObject)

                            blockList.append({"text": fieldText, "isJoinable": False, "page": layoutList[a]["page"], "bbox": layoutList[a]["bbox"], "label": "pair", "tableObject": None})

                            continue

                        partList = self._tableTitleSplit(tableObject, itemList, directionObject)

                        if len(partList) == 0:
                            partList = self._tableSpanSplit(tableObject, itemList, directionObject)

                        if len(partList) > 0:
                            blockList = blockList + partList

                            continue

                        isHeader = self._rowBoldCheck(tableObject, itemList)

                blockList.append({"text": block, "isJoinable": self._blockJoinable(layoutList[a]), "page": layoutList[a]["page"], "bbox": layoutList[a]["bbox"], "label": layoutList[a]["label"], "tableObject": tableObject, "isHeader": isHeader})

            while indexOrphan < len(lineOrphanList):
                self._orphanAppend(lineOrphanList[indexOrphan], layoutList, directionObject, blockList, secondaryList, sizeBody)

                indexOrphan += 1

            furnitureObject = self._furnitureSplit(blockList)

            return self.markdown.separatorBlock.join(self.markdown._secondaryAppend(self._blockMerge(furnitureObject["blockList"], directionObject), secondaryList + furnitureObject["textList"]))

        def __init__(self, markdown):
            self.levelLineOverlap = 0.5
            self.levelColumnGap = 1.5
            self.levelLineBreakSpace = 0.5
            self.levelPairFill = 0.85
            self.levelPairFillCount = 0.5

            self.levelTableTitleAlign = 0.5
            self.levelFieldFree = 1.0
            self.levelFieldShare = 0.8
            self.levelFieldRatio = 0.5
            self.levelTableCut = 0.25
            self.countFieldMinimum = 2
            self.headerFieldList = ["key", "value"]
            self.countBoxCell = 3
            self.levelLineSplitPitch = 1.15
            self.levelLineOutdent = 0.5
            self.levelLineOutdentMaximum = 4
            self.levelPairAlign = 0.5
            self.levelPairMatch = 0.5
            self.levelPairWidth = 12
            self.levelPairWidthRow = 16
            self.levelRowTruncated = 0.75

            self.countPairRow = 2
            self.countPairLine = 3
            self.countParagraphLine = 3
            self.countFurniture = 2
            self.countFurniturePage = 2


            self.labelPrefixObject = {
                "doc_title": "# ",
                "paragraph_title": "## "
            }

            self.labelPlaceholderList = ["image", "chart"]

            self.labelBarrierList = ["table", "header", "footer"]

            self.labelRefineList = ["doc_title", "paragraph_title", "text", "figure_title", "header"]

            self.labelPageList = ["header", "footer", "number", "footnote"]

            self.labelPairList = ["text", "aside_text"]

            self.markdown = markdown

    class Office:
        def _docxBuild(self, astPageList, tableList):
            blockList = []
            secondaryList = []

            for a in range(len(astPageList)):
                blockList = blockList + self._blockItemBuild(astPageList[a]["itemMainList"], self._tablePageCollect(tableList, astPageList[a]["number"]))
                secondaryList = secondaryList + self._secondaryBuild(astPageList[a]["itemSecondaryList"])

            return self.markdown.separatorBlock.join(self.markdown._secondaryAppend(blockList, secondaryList))

        def _tablePageCollect(self, tableList, numberPage):
            resultList = []

            for a in range(len(tableList)):
                if tableList[a]["page"] == numberPage:
                    resultList.append(tableList[a])

            return resultList

        def _blockItemBuild(self, itemList, tablePageList):
            resultList = []

            indexTable = 0
            isRow = False
            isHeader = False
            directionObject = None

            for a in range(len(itemList) + 1):
                item = itemList[a] if a < len(itemList) else None

                isRowItem = item != None and item["label"] == "tableRow"

                if isRow and (isRowItem == False or item["isStart"]):
                    resultList.append(self._tableRowWrite(tablePageList[indexTable], directionObject, isHeader))

                    indexTable += 1
                    isRow = False

                if isRowItem:
                    if isRow == False:
                        directionObject = item["direction"]
                        isHeader = item["isHeader"]

                    isRow = True

                    continue

                if item == None:
                    continue

                text = self.markdown._textEscape(item["text"])

                if item["label"] == "doc_title":
                    resultList.append(f"# {text}")
                elif item["label"] == "paragraph_title":
                    resultList.append(f"{self._headingHash(item['level'])} {text}")
                elif "isList" in item and item["isList"]:
                    resultList.append(f"{textBullet}{text}")
                else:
                    resultList.append(text)

            return resultList

        def _tableSectionList(self, cellList):
            rowObject = {}

            for a in range(len(cellList)):
                for b in range(cellList[a]["rowSpan"]):
                    rowIndex = cellList[a]["rowIndex"] + b

                    if rowIndex not in rowObject:
                        rowObject[rowIndex] = []

                    rowObject[rowIndex].append(cellList[a])

            sectionList = []

            signaturePrevious = None
            boundaryPreviousList = []

            for rowIndex in sorted(rowObject):
                rowList = sorted(rowObject[rowIndex], key=lambda cellObject: cellObject["columnIndex"])

                signature = [(cellObject["columnIndex"], cellObject["columnSpan"]) for cellObject in rowList]

                isLink = False

                for a in range(len(rowList)):
                    if rowList[a]["rowIndex"] < rowIndex:
                        isLink = True

                boundaryList = [0]

                for a in range(len(rowList)):
                    boundaryList.append(rowList[a]["columnIndex"] + rowList[a]["columnSpan"])

                isMerge = len(rowList) > 1

                for a in range(len(boundaryList)):
                    if boundaryList[a] not in boundaryPreviousList:
                        isMerge = False

                if len(sectionList) == 0 or (signature != signaturePrevious and isLink == False and isMerge == False):
                    sectionList.append({"rowList": [], "indexList": [], "isUniform": True})

                    boundaryPreviousList = []
                elif signature != signaturePrevious:
                    sectionList[len(sectionList) - 1]["isUniform"] = False

                signaturePrevious = signature
                boundaryPreviousList = boundaryPreviousList + boundaryList

                sectionList[len(sectionList) - 1]["rowList"].append(rowList)
                sectionList[len(sectionList) - 1]["indexList"].append(rowIndex)

            if len(sectionList) < 2:
                return []

            resultList = []

            for a in range(len(sectionList)):
                cellSectionList = []

                for b in range(len(sectionList[a]["rowList"])):
                    rowList = sectionList[a]["rowList"][b]

                    for c in range(len(rowList)):
                        if sectionList[a]["isUniform"]:
                            cellSectionList.append({"rowIndex": b, "columnIndex": c, "rowSpan": 1, "columnSpan": 1, "text": rowList[c]["text"]})
                        elif rowList[c]["rowIndex"] == sectionList[a]["indexList"][b]:
                            cellObject = dict(rowList[c])

                            cellObject["rowIndex"] = b

                            cellSectionList.append(cellObject)

                resultList.append(cellSectionList)

            return resultList

        def _tableRowWrite(self, tableObject, directionObject, isHeader):
            sectionList = self._tableSectionList(tableObject["cellList"])

            if len(sectionList) > 0:
                textList = []

                for a in range(len(sectionList)):
                    if self.markdown._gridSize(sectionList[a])["countColumn"] == 1:
                        for b in range(len(sectionList[a])):
                            if len(sectionList[a][b]["text"].strip()) > 0:
                                textList.append(self.markdown._textEscape(sectionList[a][b]["text"].strip()))

                        continue

                    textList.append(self._tableRowWrite({"cellList": sectionList[a]}, directionObject, isHeader and a == 0))

                return self.markdown.separatorBlock.join(textList)

            gridList = self.markdown._gridCellBuild(tableObject["cellList"])

            if directionObject["isVertical"] or directionObject["isRightToLeft"]:
                for a in range(len(gridList)):
                    gridList[a].reverse()

            return self.markdown._gridHeaderWrite(gridList, isHeader)

        def _headingHash(self, level):
            return "#" * min(level, self.levelHeadingMax)

        def _secondaryBuild(self, itemList):
            resultList = []

            for a in range(len(itemList)):
                if "path" in itemList[a]:
                    resultList.append(f"![{itemList[a]['label']}]({itemList[a]['path']})")

                    continue

                text = self.markdown._textEscape(itemList[a]["text"])

                if len(text) == 0:
                    resultList.append(f"[{itemList[a]['label']}]")

                    continue

                if itemList[a]["label"] == "chart":
                    resultList.append(self._linePrefixWrite(text, "", textBullet))

                    continue

                resultList.append(text)

            return resultList

        def _linePrefixWrite(self, text, prefixFirst, prefixRest):
            textList = text.split(self.markdown.separatorLine)

            lineList = [f"{prefixFirst}{textList[0]}"]

            for a in range(1, len(textList)):
                lineList.append(f"{prefixRest}{textList[a]}")

            return self.markdown.separatorLine.join(lineList)

        def _xlsxBuild(self, astPageList, tableList):
            blockList = []
            secondaryList = []

            for a in range(len(astPageList)):
                astPage = astPageList[a]

                for b in range(len(astPage["itemMainList"])):
                    if astPage["itemMainList"][b]["label"] == "sheetName":
                        blockList.append(f"# {self.markdown._textEscape(astPage['itemMainList'][b]['text'])}")

                secondaryList = secondaryList + self._secondaryBuild(astPage["itemSecondaryList"])

                tablePageList = self._tablePageCollect(tableList, astPage["number"])

                for b in range(len(tablePageList)):
                    blockList.append(self._sheetWrite(tablePageList[b], astPage))

            return self.markdown.separatorBlock.join(self.markdown._secondaryAppend(blockList, secondaryList))

        def _sheetWrite(self, tableObject, astPage):
            gridList = self.markdown._gridCellBuild(tableObject["cellList"])

            rowNumberList = []
            rowBoldList = []

            for a in range(len(astPage["itemMainList"])):
                if astPage["itemMainList"][a]["label"] == "tableRow":
                    rowNumberList.append(str(astPage["itemMainList"][a]["number"]))
                    rowBoldList.append(astPage["itemMainList"][a]["isBold"])

            columnList = []

            for a in range(len(gridList[0])):
                columnList.append(self.office.gridColumnLetter(a))

            if astPage["direction"]["isRightToLeft"]:
                columnList.reverse()

                for a in range(len(gridList)):
                    gridList[a].reverse()

            blockList = []
            rowList = []
            numberList = []
            boldList = []

            for a in range(len(gridList) + 1):
                if a < len(gridList) and self._rowEmptyCheck(gridList[a]) == False:
                    rowList.append(gridList[a])
                    numberList.append(rowNumberList[a])
                    boldList.append(rowBoldList[a])

                    continue

                if len(rowList) > 0:
                    blockList.append(self._sheetBlockWrite(rowList, numberList, columnList, boldList))

                rowList = []
                numberList = []
                boldList = []

            return self.markdown.separatorBlock.join(blockList)

        def _rowEmptyCheck(self, rowList):
            for a in range(len(rowList)):
                if rowList[a] != self.markdown.textCellEmpty:
                    return False

            return True

        def _sheetBlockWrite(self, rowList, numberList, columnList, boldList):
            blockList = []

            groupList = self._columnGroupBuild(rowList)

            for a in range(len(groupList)):
                rowGroupList = []
                numberGroupList = []
                boldGroupList = []

                for b in range(len(rowList)):
                    cellList = rowList[b][groupList[a][0]:groupList[a][1]]

                    if self._rowEmptyCheck(cellList) == False:
                        rowGroupList.append(cellList)
                        numberGroupList.append(numberList[b])
                        boldGroupList.append(boldList[b])

                blockList.append(self._sheetTableWrite(rowGroupList, numberGroupList, columnList[groupList[a][0]:groupList[a][1]], boldGroupList))

            return self.markdown.separatorBlock.join(blockList)

        def _columnGroupBuild(self, rowList):
            resultList = []

            indexStart = -1

            for a in range(len(rowList[0]) + 1):
                isEmpty = a == len(rowList[0])

                if isEmpty == False:
                    isEmpty = True

                    for b in range(len(rowList)):
                        if rowList[b][a] != self.markdown.textCellEmpty:
                            isEmpty = False

                            break

                if isEmpty == False and indexStart < 0:
                    indexStart = a
                elif isEmpty and indexStart >= 0:
                    resultList.append([indexStart, a])

                    indexStart = -1

            return resultList

        def _sheetTableWrite(self, rowList, numberList, columnList, boldList):
            isHeader = len(rowList) > 1 and boldList[0] and True not in boldList[1:]

            headerObject = self.markdown._gridHeaderSplit(rowList, isHeader)

            headerList = [self.labelRow] + columnList

            if headerObject["bodyList"] is not rowList:
                headerList = [self.labelRow] + headerObject["headerList"]

            numberBodyList = numberList[len(rowList) - len(headerObject["bodyList"]):]

            bodyList = []

            for a in range(len(headerObject["bodyList"])):
                bodyList.append([f"{self.prefixRow}{numberBodyList[a]}"] + headerObject["bodyList"][a])

            return self.markdown.separatorBlock.join(headerObject["captionList"] + [self.markdown._tableWrite(headerList, bodyList)])

        def _pptxBuild(self, astPageList, tableList):
            blockList = []
            secondaryList = []

            for a in range(len(astPageList)):
                blockList = blockList + self._blockItemBuild(astPageList[a]["itemMainList"], self._tablePageCollect(tableList, astPageList[a]["number"]))

                itemSecondaryList = astPageList[a]["itemSecondaryList"]

                if len(itemSecondaryList) == 0:
                    continue

                lineList = [f"{textBullet}Slide {astPageList[a]['number']}"]
                textList = self._secondaryBuild(itemSecondaryList)

                for b in range(len(textList)):
                    lineList.append(self._linePrefixWrite(textList[b], self.prefixChild, self.prefixChildRest))

                secondaryList.append(self.markdown.separatorLine.join(lineList))

            return self.markdown.separatorBlock.join(self.markdown._secondaryAppend(blockList, secondaryList))

        def execute(self, resultObject, extension):
            buildObject = {
                ".docx": self._docxBuild,
                ".xlsx": self._xlsxBuild,
                ".pptx": self._pptxBuild
            }

            return buildObject[extension](resultObject["astPageList"], resultObject["tableList"])

        def __init__(self, markdown, office):
            self.prefixChild = "  - "
            self.prefixChildRest = "    "

            self.levelHeadingMax = 6

            self.labelRow = "excel_row"
            self.prefixRow = "R"

            self.markdown = markdown
            self.office = office
