import sys
import icu

sys.dont_write_bytecode = True

# Source
from helper import privateUseCheck, tokenFirstLength, textNormalize, spacelessCheck, whitespaceCheck, spaceSkipCheck, sentenceEndCheck, boxCenterInsideCheck, rangeOverlapRatio, flowGapCalculate

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

                if isText and self._headerColumnCheck(self._headerRowBuild(gridList, a, countHeader), gridList[a + countHeader:]):
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

            if indexTitle >= 0 and sizeBest >= sizeBody * self.levelTitleSize:
                layoutList[indexTitle]["label"] = "doc_title"

        def _sizeDominant(self, itemList):
            countObject = {}

            for a in range(len(itemList)):
                if "fontSize" not in itemList[a]:
                    continue

                countObject[itemList[a]["fontSize"]] = countObject.get(itemList[a]["fontSize"], 0) + len(itemList[a]["text"])

            result = 0
            countBest = 0

            for size in countObject:
                if countObject[size] > countBest:
                    result = size
                    countBest = countObject[size]

            return result

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
            if size < sizeBody * self.levelTitleSize or len(lineList) > 1:
                return False

            text = self._lineText(lineList[0], directionObject)

            return len(text) <= self.levelTitleLength and sentenceEndCheck(text, self.levelReferenceLength) == False

        def _lineTitleWrite(self, lineObject, directionObject, sizeBody):
            text = self._lineText(lineObject, directionObject)

            size = self._sizeDominant(lineObject["itemList"])

            if sizeBody > 0 and size > 0 and self._listMarkCheck(text) == False and self._titleCheck([lineObject], directionObject, size, sizeBody):
                return f"{self.labelPrefixObject['paragraph_title']}{text}"

            return text

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

                crossList = self._crossRange(bboxList, directionObject[itemSortedList[a]["page"]])

                isAdded = False

                for b in range(len(resultList)):
                    if resultList[b]["page"] != itemSortedList[a]["page"]:
                        continue

                    if rangeOverlapRatio(crossList[0], crossList[1], resultList[b]["cross1"], resultList[b]["cross2"]) < self.levelLineOverlap:
                        continue

                    resultList[b]["cross1"] = min(resultList[b]["cross1"], crossList[0])
                    resultList[b]["cross2"] = max(resultList[b]["cross2"], crossList[1])

                    resultList[b]["bbox"] = self._bboxExpand(resultList[b]["bbox"], bboxList)

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

        def _crossRange(self, bboxList, directionPageObject):
            if directionPageObject["isVertical"]:
                return [bboxList[0], bboxList[2]]

            return [bboxList[1], bboxList[3]]

        def _columnRange(self, bboxList, directionPageObject):
            if directionPageObject["isVertical"]:
                return [bboxList[1], bboxList[3]]

            return [bboxList[0], bboxList[2]]

        def _bboxExpand(self, bboxList, bboxOtherList):
            return [
                min(bboxList[0], bboxOtherList[0]),
                min(bboxList[1], bboxOtherList[1]),
                max(bboxList[2], bboxOtherList[2]),
                max(bboxList[3], bboxOtherList[3])
            ]

        def _lineFlow(self, lineObject, layoutList, directionObject):
            directionPageObject = directionObject[lineObject["page"]]

            columnLineList = self._columnRange(lineObject["bbox"], directionPageObject)
            crossLineList = self._crossRange(lineObject["bbox"], directionPageObject)

            distanceBest = -1
            flowResult = "main"

            for a in range(len(layoutList)):
                if layoutList[a]["page"] != lineObject["page"]:
                    continue

                columnList = self._columnRange(layoutList[a]["bbox"], directionPageObject)

                if min(columnLineList[1], columnList[1]) <= max(columnLineList[0], columnList[0]):
                    continue

                crossList = self._crossRange(layoutList[a]["bbox"], directionPageObject)

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
                result = f"- {result[1:].lstrip()}"

            return self.markdown._textEscape(result)

        def _spaceCheck(self, bboxPreviousList, bboxList, textPrevious, text, directionPageObject):
            if spaceSkipCheck(textPrevious, text):
                return False

            gapObject = flowGapCalculate(bboxPreviousList, bboxList, directionPageObject)

            return gapObject["gap"] >= gapObject["size"] * self.levelSpaceGap

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
                    return self._tableWrite(tableObject, itemList, directionObject)

            text = self._textBuild(itemList, layoutObject["page"], layoutObject["bbox"], directionObject)

            if len(text) == 0:
                return ""

            if label not in self.labelPrefixObject:
                return text

            return f"{self.labelPrefixObject[label]}{text.replace(self.markdown.separatorLine, self.markdown.separatorText)}"

        def _formWrite(self, layoutObject, formObject, formWrittenList):
            label = layoutObject["label"]

            if label in self.labelPlaceholderList:
                return f"![{label}]({layoutObject['path']})"

            if label != "table" or layoutObject["page"] in formWrittenList:
                return ""

            formWrittenList.append(layoutObject["page"])

            return formObject[layoutObject["page"]]

        def _tableFind(self, tableList, layoutObject):
            for a in range(len(tableList)):
                if tableList[a]["page"] != layoutObject["page"]:
                    continue

                if tableList[a]["bbox"] != layoutObject["bbox"]:
                    continue

                return tableList[a]

            return None

        def _tableWrite(self, tableObject, itemList, directionObject):
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
            cellList = tableObject["cellList"]

            sizeObject = self.markdown._gridSize(cellList)

            gridList = self.markdown._gridEmpty(sizeObject["countRow"], sizeObject["countColumn"])

            for a in range(len(cellList)):
                text = self.markdown._cellEscape(cellList[a]["text"])

                if len(text) == 0:
                    continue

                self.markdown._gridPut(gridList, cellList[a]["rowIndex"], cellList[a]["columnIndex"], text)

            self.markdown._gridSpanFill(cellList, gridList)

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

        def _textBuild(self, itemList, numberPage, bboxList, directionObject):
            return self._lineListWrite(self._lineGroup(self._itemInsideCollect(itemList, numberPage, bboxList), directionObject), directionObject)

        def _lineListWrite(self, lineList, directionObject):
            result = ""

            isColumnGap = len(lineList) < self.countParagraphLine or self._lineFillCheck(lineList, directionObject) == False

            for a in range(len(lineList)):
                text = self._lineText(lineList[a], directionObject, isColumnGap)

                if a > 0 and (self._listMarkCheck(text) or self._lineBreakCheck(directionObject, lineList, a, text)):
                    result += f"{self.markdown.separatorLine}{text}"
                else:
                    result = self.markdown._textJoin([result, text])

            return result

        def _lineBreakCheck(self, directionObject, lineList, index, text):
            directionPageObject = directionObject[lineList[index]["page"]]

            columnList = self._columnRange(lineList[index]["bbox"], directionPageObject)
            columnPreviousList = self._columnRange(lineList[index - 1]["bbox"], directionPageObject)

            edgeStart = columnList[0]
            edgeEnd = columnList[1]

            for a in range(len(lineList)):
                columnOtherList = self._columnRange(lineList[a]["bbox"], directionPageObject)

                edgeStart = min(edgeStart, columnOtherList[0])
                edgeEnd = max(edgeEnd, columnOtherList[1])

            available = columnPreviousList[0] - edgeStart if directionPageObject["isRightToLeft"] else edgeEnd - columnPreviousList[1]

            crossList = self._crossRange(lineList[index]["bbox"], directionPageObject)

            widthToken = (columnList[1] - columnList[0]) * tokenFirstLength(text) / len(text)

            return available > widthToken + (crossList[1] - crossList[0]) * self.levelLineBreakSpace

        def _pairBuild(self, layoutList, directionObject, itemList):
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

                columnList = self._columnRange(lineList[a]["bbox"], directionPageObject)
                crossList = self._crossRange(lineList[a]["bbox"], directionPageObject)

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

                    rowList.append([self.markdown._cellEscape(self._lineListWrite(pairObject["lineList"], directionObject)), self.markdown._cellEscape(self._lineListWrite(pairObject["lineOtherList"], directionObject))])

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

                crossList = self._crossRange(lineList[a]["bbox"], directionPageObject)

                indexMatch = -1

                for b in range(len(lineOtherList)):
                    crossOtherList = self._crossRange(lineOtherList[b]["bbox"], directionPageObject)

                    if rangeOverlapRatio(crossList[0], crossList[1], crossOtherList[0], crossOtherList[1]) >= self.levelLineOverlap:
                        indexMatch = b

                        break

                resultList.append(indexMatch)

            return resultList

        def _lineFillCheck(self, lineList, directionObject):
            edgeStart = -1
            edgeEnd = -1

            for a in range(len(lineList)):
                columnList = self._columnRange(lineList[a]["bbox"], directionObject[lineList[a]["page"]])

                edgeStart = columnList[0] if a == 0 else min(edgeStart, columnList[0])
                edgeEnd = columnList[1] if a == 0 else max(edgeEnd, columnList[1])

            count = 0

            for a in range(len(lineList)):
                columnList = self._columnRange(lineList[a]["bbox"], directionObject[lineList[a]["page"]])

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

                    key = textNormalize(block["text"])

                    if key not in textPageObject:
                        textPageObject[key] = []

                    if numberPage not in textPageObject[key]:
                        textPageObject[key].append(numberPage)

            resultObject = {"blockList": [], "textList": []}

            textWrittenList = []

            for a in range(len(blockList)):
                key = textNormalize(blockList[a]["text"])

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

                    if blockPrevious["isJoinable"] and blockList[a]["isJoinable"] and self._pageBreakCheck(blockPrevious, blockList[a], directionObject) and sentenceEndCheck(blockPrevious["text"], self.levelReferenceLength) == False:
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

                if overlapBest < self.levelColumnOverlap or indexBest in resultList:
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

            columnPreviousList = self._columnRange(blockPrevious["bbox"], directionObject[blockPrevious["page"]])
            columnList = self._columnRange(blockObject["bbox"], directionObject[blockObject["page"]])

            return rangeOverlapRatio(columnPreviousList[0], columnPreviousList[1], columnList[0], columnList[1]) >= self.levelColumnOverlap

        def _orphanAppend(self, lineObject, layoutList, directionObject, blockList, secondaryList, sizeBody):
            if self._lineFlow(lineObject, layoutList, directionObject) == "main":
                blockList.append({"text": self._lineTitleWrite(lineObject, directionObject, sizeBody), "isJoinable": False, "page": lineObject["page"], "bbox": None, "label": "text", "tableObject": None})

                return

            secondaryList.append(self._lineText(lineObject, directionObject))

        def execute(self, resultObject, extension):
            layoutList = resultObject["layoutList"]
            tableList = resultObject["tableList"]
            itemList = resultObject["itemList"]

            directionObject = {}

            for a in range(len(resultObject["directionList"])):
                directionObject[resultObject["directionList"][a]["page"]] = resultObject["directionList"][a]

            self._labelRefine(layoutList, itemList, directionObject)

            formObject = {}

            for a in range(len(resultObject["formList"])):
                formObject[resultObject["formList"][a]["page"]] = resultObject["formList"][a]["text"]

            formWrittenList = []

            itemFlowList = []

            for a in range(len(itemList)):
                if itemList[a]["page"] not in formObject:
                    itemFlowList.append(itemList[a])

            blockList = []
            secondaryList = []

            lineOrphanList = self._lineGroup(self._itemOrphanCollect(itemFlowList, layoutList), directionObject)

            pairObject = self._pairBuild(layoutList, directionObject, itemFlowList)

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

                if layoutList[a]["page"] in formObject:
                    block = self._formWrite(layoutList[a], formObject, formWrittenList)
                else:
                    block = self._blockWrite(layoutList[a], tableList, itemList, directionObject)

                if len(block) == 0:
                    continue

                if layoutList[a]["flow"] == "secondary":
                    secondaryList.append(block)

                    continue

                tableObject = None
                isHeader = False

                if layoutList[a]["label"] == "table" and layoutList[a]["page"] not in formObject:
                    tableObject = self._tableFind(tableList, layoutList[a])

                    if tableObject != None:
                        isHeader = self._rowBoldCheck(tableObject, itemList)

                blockList.append({"text": block, "isJoinable": self._blockJoinable(layoutList[a]), "page": layoutList[a]["page"], "bbox": layoutList[a]["bbox"], "label": layoutList[a]["label"], "tableObject": tableObject, "isHeader": isHeader})

            while indexOrphan < len(lineOrphanList):
                self._orphanAppend(lineOrphanList[indexOrphan], layoutList, directionObject, blockList, secondaryList, sizeBody)

                indexOrphan += 1

            furnitureObject = self._furnitureSplit(blockList)

            return self.markdown.separatorBlock.join(self.markdown._secondaryAppend(self._blockMerge(furnitureObject["blockList"], directionObject), secondaryList + furnitureObject["textList"]))

        def __init__(self, markdown):
            self.levelLineOverlap = 0.5
            self.levelColumnOverlap = 0.5
            self.levelSpaceGap = 0.15
            self.levelColumnGap = 1.5
            self.levelLineBreakSpace = 0.5
            self.levelPairFill = 0.85
            self.levelPairFillCount = 0.5

            self.levelTitleSize = 1.15
            self.levelTitleLength = 120
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

            self.levelReferenceLength = 20

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
                blockList = blockList + self._blockBuild(astPageList[a]["itemMainList"], self._tablePageCollect(tableList, astPageList[a]["number"]))
                secondaryList = secondaryList + self._secondaryBuild(astPageList[a]["itemSecondaryList"])

            return self.markdown.separatorBlock.join(self.markdown._secondaryAppend(blockList, secondaryList))

        def _tablePageCollect(self, tableList, numberPage):
            resultList = []

            for a in range(len(tableList)):
                if tableList[a]["page"] == numberPage:
                    resultList.append(tableList[a])

            return resultList

        def _blockBuild(self, itemList, tablePageList):
            resultList = []

            indexTable = 0
            isRow = False
            isHeader = False
            directionObject = None

            for a in range(len(itemList) + 1):
                item = itemList[a] if a < len(itemList) else None

                if item != None and item["label"] == "tableRow":
                    if isRow == False:
                        directionObject = item["direction"]
                        isHeader = item["isHeader"]

                    isRow = True

                    continue

                if isRow:
                    resultList.append(self._tableWrite(tablePageList[indexTable], directionObject, isHeader))

                    indexTable += 1
                    isRow = False

                if item == None:
                    continue

                text = self.markdown._textEscape(item["text"])

                if item["label"] == "doc_title":
                    resultList.append(f"# {text}")
                elif item["label"] == "paragraph_title":
                    resultList.append(f"{self._headingHash(item['level'])} {text}")
                elif "isList" in item and item["isList"]:
                    resultList.append(f"- {text}")
                else:
                    resultList.append(text)

            return resultList

        def _tableWrite(self, tableObject, directionObject, isHeader):
            gridList = self._gridFill(tableObject["cellList"])

            if directionObject["isVertical"] or directionObject["isRightToLeft"]:
                for a in range(len(gridList)):
                    gridList[a].reverse()

            return self.markdown._gridHeaderWrite(gridList, isHeader)

        def _gridFill(self, cellList):
            sizeObject = self.markdown._gridSize(cellList)

            resultList = self.markdown._gridEmpty(sizeObject["countRow"], sizeObject["countColumn"])

            for a in range(len(cellList)):
                text = self.markdown._cellEscape(cellList[a]["text"])

                if len(text) == 0:
                    continue

                self.markdown._gridPut(resultList, cellList[a]["rowIndex"], cellList[a]["columnIndex"], text)

            self.markdown._gridSpanFill(cellList, resultList)

            return resultList

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
                    resultList.append(self._chartWrite(text))

                    continue

                resultList.append(text)

            return resultList

        def _chartWrite(self, text):
            textList = text.split(self.markdown.separatorLine)

            lineList = [textList[0]]

            for a in range(1, len(textList)):
                lineList.append(f"- {textList[a]}")

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
            gridList = self._gridFill(tableObject["cellList"])

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
                blockList = blockList + self._blockBuild(astPageList[a]["itemMainList"], self._tablePageCollect(tableList, astPageList[a]["number"]))

                itemSecondaryList = astPageList[a]["itemSecondaryList"]

                if len(itemSecondaryList) == 0:
                    continue

                lineList = [f"- Slide {astPageList[a]['number']}"]
                textList = self._secondaryBuild(itemSecondaryList)

                for b in range(len(textList)):
                    lineList.append(self._itemChildWrite(textList[b]))

                secondaryList.append(self.markdown.separatorLine.join(lineList))

            return self.markdown.separatorBlock.join(self.markdown._secondaryAppend(blockList, secondaryList))

        def _itemChildWrite(self, text):
            textList = text.split(self.markdown.separatorLine)

            lineList = [f"  - {textList[0]}"]

            for a in range(1, len(textList)):
                lineList.append(f"    {textList[a]}")

            return self.markdown.separatorLine.join(lineList)

        def execute(self, resultObject, extension):
            buildObject = {
                ".docx": self._docxBuild,
                ".xlsx": self._xlsxBuild,
                ".pptx": self._pptxBuild
            }

            return buildObject[extension](resultObject["astPageList"], resultObject["tableList"])

        def __init__(self, markdown, office):
            self.levelHeadingMax = 6

            self.labelRow = "excel_row"
            self.prefixRow = "R"

            self.markdown = markdown
            self.office = office
