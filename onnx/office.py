import sys
import os
import re
import cv2
import icu
import decimal
import numpy
import zipfile
import datetime
import xml.etree.ElementTree

sys.dont_write_bytecode = True

# Source
from helper import spacelessCheck, sentenceEndCheck, textNormalize, rangeOverlapRatio, astWrite, mediaImageWrite

class Office:
    def _xmlRootBuild(self, pathFile, zipFile):
        result = None

        if pathFile in zipFile.namelist():
            result = xml.etree.ElementTree.fromstring(zipFile.read(pathFile))

        return result

    def _xmlNodeValue(self, node, namespace):
        return node.attrib.get(f"{{{namespace}}}val", "")

    def _xmlNodeTag(self, node):
        return node.tag.split("}")[1] if "}" in node.tag else node.tag

    def _xmlChartText(self, chartRootNode):
        namespaceChart = self.namespaceChart
        namespaceDrawing = self.namespaceDrawing

        result = "chart"

        plotAreaNode = chartRootNode.find(f".//{{{namespaceChart}}}plotArea")

        if plotAreaNode is not None:
            for node in plotAreaNode:
                if self._xmlNodeTag(node).endswith("Chart"):
                    result = self._xmlNodeTag(node)

                    break

        titleText = ""

        titleNode = chartRootNode.find(f".//{{{namespaceChart}}}title")

        if titleNode is not None:
            for node in titleNode.iter(f"{{{namespaceDrawing}}}t"):
                titleText += node.text if node.text is not None else ""

        if titleText != "":
            result += f" - {titleText}"

        for serieNode in chartRootNode.iter(f"{{{namespaceChart}}}ser"):
            nameText = ""

            textNode = serieNode.find(f"{{{namespaceChart}}}tx")

            if textNode is not None:
                for node in textNode.iter(f"{{{namespaceChart}}}v"):
                    if node.text is not None:
                        nameText = node.text

                    break

            categoryObject = {}

            categoryNode = serieNode.find(f"{{{namespaceChart}}}cat")

            if categoryNode is not None:
                for node in categoryNode.iter(f"{{{namespaceChart}}}pt"):
                    valueNode = node.find(f"{{{namespaceChart}}}v")

                    if valueNode is not None and valueNode.text is not None:
                        categoryObject[node.attrib.get("idx", "")] = valueNode.text

            pairList = []

            valueParentNode = serieNode.find(f"{{{namespaceChart}}}val")

            if valueParentNode is not None:
                for node in valueParentNode.iter(f"{{{namespaceChart}}}pt"):
                    valueNode = node.find(f"{{{namespaceChart}}}v")

                    if valueNode is not None and valueNode.text is not None:
                        index = node.attrib.get("idx", "")

                        categoryText = categoryObject[index] if index in categoryObject else index

                        pairList.append(f"{categoryText}={valueNode.text}")

            serieText = ", ".join(pairList)

            if nameText != "":
                result += f"\n{nameText}: {serieText}"
            elif serieText != "":
                result += f"\n{serieText}"

        return result

    def _textCollect(self, node, characterObject, tagSkip):
        result = ""

        tag = self._xmlNodeTag(node)

        if tag == tagSkip:
            return result

        if tag == "t":
            result += node.text if node.text is not None else ""
        elif tag in characterObject:
            result += characterObject[tag]

        for childNode in node:
            result += self._textCollect(childNode, characterObject, tagSkip)

        return result

    def _paragraphText(self, paragraphNode, characterObject, tagSkip):
        return re.sub(self.patternTabulation, " ", self._textCollect(paragraphNode, characterObject, tagSkip)).strip()

    def _relationshipBuild(self, pathFile, zipFile):
        resultObject = {}

        relationshipRootNode = self._xmlRootBuild(f"{os.path.dirname(pathFile)}/_rels/{os.path.basename(pathFile)}.rels", zipFile)

        if relationshipRootNode is not None:
            for node in relationshipRootNode.iter(f"{{{self.namespacePackage}}}Relationship"):
                target = node.attrib.get("Target", "")

                resultObject[node.attrib.get("Id", "")] = {
                    "path": target[1:] if target.startswith("/") else os.path.normpath(f"{os.path.dirname(pathFile)}/{target}"),
                    "type": node.attrib.get("Type", "")
                }

        return resultObject

    def _mediaWrite(self, zipFile, pathMedia, pathOutput):
        byteList = zipFile.read(pathMedia)

        image = cv2.imdecode(numpy.frombuffer(byteList, numpy.uint8), cv2.IMREAD_UNCHANGED)

        if image is not None:
            return mediaImageWrite(image, pathOutput)

        fileName = os.path.basename(pathMedia)

        os.makedirs(f"{pathOutput}media/", exist_ok=True)

        with open(f"{pathOutput}media/{fileName}", "wb") as file:
            file.write(byteList)

        return f"media/{fileName}"

    def _flowAssign(self, itemMainList, itemSecondaryList):
        for a in range(len(itemMainList)):
            itemMainList[a]["flow"] = "main"
            itemMainList[a]["order"] = a + 1

        for a in range(len(itemSecondaryList)):
            itemSecondaryList[a]["flow"] = "secondary"
            itemSecondaryList[a]["order"] = a + 1

    def _layoutBuild(self, astPageList):
        resultList = []

        for a in range(len(astPageList)):
            flowObject = {"main": astPageList[a]["itemMainList"], "secondary": astPageList[a]["itemSecondaryList"]}

            for flow in flowObject:
                itemList = flowObject[flow]

                for b in range(len(itemList)):
                    resultList.append({
                        "id": len(resultList) + 1,
                        "page": astPageList[a]["number"],
                        "flow": flow,
                        "label": itemList[b]["label"],
                        "score": 0.0,
                        "bbox": [0, 0, 0, 0],
                        "centerPoint": {"x": 0, "y": 0},
                        "path": itemList[b]["path"] if "path" in itemList[b] else ""
                    })

        return resultList

    def _tableXlsxBuild(self, astPageList):
        resultList = []

        for a in range(len(astPageList)):
            astPage = astPageList[a]

            rowItemList = []

            for b in range(len(astPage["itemMainList"])):
                if astPage["itemMainList"][b]["label"] == "tableRow":
                    rowItemList.append(astPage["itemMainList"][b])

            if len(rowItemList) == 0:
                continue

            mergeObject = self._gridMergeObject(astPage["mergeList"] if "mergeList" in astPage else [])

            cellList = []

            for b in range(len(rowItemList)):
                rowNumber = rowItemList[b]["number"]

                for c in range(len(rowItemList[b]["cellList"])):
                    spanObject = mergeObject[(rowNumber, c)] if (rowNumber, c) in mergeObject else {"rowSpan": 1, "columnSpan": 1}

                    if spanObject is None:
                        continue

                    cellList.append(self._cellResultBuild({
                        "rowIndex": b,
                        "columnIndex": c,
                        "rowSpan": spanObject["rowSpan"],
                        "columnSpan": spanObject["columnSpan"],
                        "text": rowItemList[b]["cellList"][c]
                    }))

            resultList.append(self._tableResultBuild(resultList, astPage["number"], cellList))

        return resultList

    def _cellResultBuild(self, cellObject):
        return {
            "rowIndex": cellObject["rowIndex"],
            "columnIndex": cellObject["columnIndex"],
            "rowSpan": cellObject["rowSpan"],
            "columnSpan": cellObject["columnSpan"],
            "bbox": [0, 0, 0, 0],
            "centerPoint": {"x": 0, "y": 0},
            "text": cellObject["text"]
        }

    def _tableResultBuild(self, resultList, numberPage, cellList):
        return {
            "id": len(resultList) + 1,
            "page": numberPage,
            "type": "office",
            "bbox": [0, 0, 0, 0],
            "centerPoint": {"x": 0, "y": 0},
            "cellList": cellList
        }

    def _gridMergeObject(self, mergeList):
        resultObject = {}

        for a in range(len(mergeList)):
            referenceList = mergeList[a].split(":")

            if len(referenceList) != 2:
                continue

            columnStart = self._gridColumnIndex(referenceList[0])
            columnEnd = self._gridColumnIndex(referenceList[1])
            rowStart = self._gridRowNumber(referenceList[0])
            rowEnd = self._gridRowNumber(referenceList[1])

            for b in range(rowStart, rowEnd + 1):
                for c in range(columnStart, columnEnd + 1):
                    if b == rowStart and c == columnStart:
                        resultObject[(b, c)] = {"rowSpan": rowEnd - rowStart + 1, "columnSpan": columnEnd - columnStart + 1}
                    else:
                        resultObject[(b, c)] = None

        return resultObject

    def _gridColumnIndex(self, reference):
        result = 0

        for a in range(len(reference)):
            character = reference[a].upper()

            if character < "A" or character > "Z":
                break

            result = result * 26 + (ord(character) - 64)

        return max(0, result - 1)

    def _gridRowNumber(self, reference):
        result = ""

        for a in range(len(reference)):
            if reference[a] >= "0" and reference[a] <= "9":
                result += reference[a]

        return int(result)

    def _tableBuild(self, astPageList):
        resultList = []

        for a in range(len(astPageList)):
            itemList = astPageList[a]["itemMainList"]

            rowList = []

            for b in range(len(itemList) + 1):
                if b < len(itemList) and itemList[b]["label"] == "tableRow":
                    rowList.append(itemList[b])

                    continue

                if len(rowList) == 0:
                    continue

                cellList = []

                gridList = self._gridBuild(rowList)

                for c in range(len(gridList)):
                    cellList.append(self._cellResultBuild(gridList[c]))

                resultList.append(self._tableResultBuild(resultList, astPageList[a]["number"], cellList))

                rowList = []

        return resultList

    def _gridBuild(self, rowList):
        occupiedObject = {}

        resultList = []

        for a in range(len(rowList)):
            cellList = rowList[a]["cellList"]

            columnIndex = 0

            for b in range(len(cellList)):
                while (a, columnIndex) in occupiedObject:
                    columnIndex += 1

                rowSpan = cellList[b]["rowSpan"]
                columnSpan = cellList[b]["columnSpan"]

                for c in range(rowSpan):
                    for d in range(columnSpan):
                        occupiedObject[(a + c, columnIndex + d)] = True

                resultList.append({
                    "rowIndex": a,
                    "columnIndex": columnIndex,
                    "rowSpan": rowSpan,
                    "columnSpan": columnSpan,
                    "text": cellList[b]["text"]
                })

                columnIndex += columnSpan

        return resultList

    def _itemBuild(self, astPageList):
        resultList = []

        for a in range(len(astPageList)):
            itemList = astPageList[a]["itemMainList"] + astPageList[a]["itemSecondaryList"]

            for b in range(len(itemList)):
                if len(itemList[b]["text"]) == 0:
                    continue

                resultList.append({
                    "id": len(resultList) + 1,
                    "page": astPageList[a]["number"],
                    "bbox": [0, 0, 0, 0],
                    "centerPoint": {"x": 0, "y": 0},
                    "text": itemList[b]["text"]
                })

        return resultList

    def gridColumnLetter(self, index):
        result = ""

        value = index + 1

        while value > 0:
            remainder = (value - 1) % 26

            result = chr(65 + remainder) + result

            value = (value - 1) // 26

        return result

    def execute(self, pathInput, pathOutput, extension):
        astPageList = self.readerObject[extension].execute(pathInput, pathOutput)["pageList"]

        resultObject = {
            "pageCount": len(astPageList),
            "astPageList": astPageList,
            "layoutList": self._layoutBuild(astPageList),
            "tableList": self._tableXlsxBuild(astPageList) if extension == ".xlsx" else self._tableBuild(astPageList),
            "itemList": self._itemBuild(astPageList)
        }

        return resultObject

    def __init__(self, isDebug):
        self.isDebug = isDebug

        self.namespaceDrawing = "http://schemas.openxmlformats.org/drawingml/2006/main"
        self.namespaceChart = "http://schemas.openxmlformats.org/drawingml/2006/chart"
        self.namespaceRelationship = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        self.namespacePackage = "http://schemas.openxmlformats.org/package/2006/relationships"

        self.valueFalseList = ["0", "false"]

        self.patternTabulation = r"[ ]*\t[ \t]*"

        self.readerObject = {
            ".docx": Office.Docx(self),
            ".xlsx": Office.Xlsx(self),
            ".pptx": Office.Pptx(self)
        }

    class Docx:
        def _styleBuild(self, styleRootNode):
            resultObject = {}

            for styleNode in styleRootNode.iter(f"{{{self.namespaceMain}}}style"):
                styleId = styleNode.attrib.get(f"{{{self.namespaceMain}}}styleId", "")

                if styleId != "":
                    outlineLevel = -1

                    outlineNode = styleNode.find(f"{{{self.namespaceMain}}}pPr/{{{self.namespaceMain}}}outlineLvl")

                    if outlineNode is not None and self.office._xmlNodeValue(outlineNode, self.namespaceMain) != "":
                        outlineLevel = int(self.office._xmlNodeValue(outlineNode, self.namespaceMain))

                    name = ""

                    nameNode = styleNode.find(f"{{{self.namespaceMain}}}name")

                    if nameNode is not None:
                        name = self.office._xmlNodeValue(nameNode, self.namespaceMain)

                    numberingNode = styleNode.find(f"{{{self.namespaceMain}}}pPr/{{{self.namespaceMain}}}numPr/{{{self.namespaceMain}}}numId")

                    basedNode = styleNode.find(f"{{{self.namespaceMain}}}basedOn")

                    resultObject[styleId] = {
                        "outlineLevel": outlineLevel,
                        "name": name,
                        "numbering": self.office._xmlNodeValue(numberingNode, self.namespaceMain) if numberingNode is not None else "",
                        "based": self.office._xmlNodeValue(basedNode, self.namespaceMain) if basedNode is not None else ""
                    }

            return resultObject

        def _noteMarkWrite(self, rootNode):
            for node in rootNode.iter():
                tag = self.office._xmlNodeTag(node)

                if tag in self.notePrefixObject:
                    node.text = f"[^{self.notePrefixObject[tag]}{node.attrib.get(f'{{{self.namespaceMain}}}id', '')}]"
                    node.tag = f"{{{self.namespaceMain}}}t"

        def _fallbackRemove(self, node):
            for child in list(node):
                if self.office._xmlNodeTag(child) == "Fallback":
                    node.remove(child)
                else:
                    self._fallbackRemove(child)

        def _blockBuild(self, containerNode, styleObject, sizeDocument):
            resultList = []

            for node in containerNode:
                tag = self.office._xmlNodeTag(node)

                blockList = []

                if tag == "p":
                    blockList = self._blockParagraph(node, styleObject, False, sizeDocument)
                elif tag == "tbl":
                    blockList = self._blockTable(node, styleObject, sizeDocument)
                elif tag != "sectPr":
                    blockList = self._blockBuild(node, styleObject, sizeDocument)

                for a in range(len(blockList)):
                    resultList.append(blockList[a])

            return resultList

        def _blockParagraph(self, paragraphNode, styleObject, isWrapped, sizeDocument):
            resultList = []

            text = self.office._paragraphText(paragraphNode, self.characterObject, self.tagSkipText)

            if len(text) > 0:
                style = self._paragraphStyle(paragraphNode)
                styleDetailObject = styleObject.get(style, {"outlineLevel": -1, "name": "", "numbering": "", "based": ""})

                outlineLevel = self._paragraphOutlineLevel(paragraphNode)

                if outlineLevel == -1:
                    outlineLevel = styleDetailObject["outlineLevel"]

                resultList.append({
                    "kind": "paragraph",
                    "text": text,
                    "size": self._paragraphSize(sizeDocument, paragraphNode),
                    "style": style,
                    "styleName": styleDetailObject["name"],
                    "outlineLevel": outlineLevel,
                    "isList": self._paragraphNumberingCheck(paragraphNode, style, styleObject),
                    "isAside": isWrapped and len(text) <= self.levelAsideLength,
                    "isContinuation": False,
                    "isWrapped": isWrapped
                })

            drawingList = self._paragraphDrawingCollect(paragraphNode)

            for a in range(len(drawingList)):
                resultList.append(drawingList[a])

            for node in paragraphNode.iter():
                if self.office._xmlNodeTag(node) == "txbxContent":
                    textboxList = self._blockWrapped(node, styleObject, sizeDocument)

                    for a in range(len(textboxList)):
                        resultList.append(textboxList[a])

            return resultList

        def _paragraphStyle(self, paragraphNode):
            result = ""

            for node in paragraphNode.iter(f"{{{self.namespaceMain}}}pStyle"):
                result = self.office._xmlNodeValue(node, self.namespaceMain)

            return result

        def _paragraphOutlineLevel(self, paragraphNode):
            result = -1

            for node in paragraphNode.iter(f"{{{self.namespaceMain}}}outlineLvl"):
                if self.office._xmlNodeValue(node, self.namespaceMain) != "":
                    result = int(self.office._xmlNodeValue(node, self.namespaceMain))

            return result

        def _paragraphSize(self, sizeDocument, paragraphNode):
            sizeDefault = sizeDocument

            sizeDefaultNode = paragraphNode.find(f"{{{self.namespaceMain}}}pPr/{{{self.namespaceMain}}}rPr/{{{self.namespaceMain}}}sz")

            if sizeDefaultNode is not None and self.office._xmlNodeValue(sizeDefaultNode, self.namespaceMain) != "":
                sizeDefault = float(self.office._xmlNodeValue(sizeDefaultNode, self.namespaceMain))

            countObject = {}

            for runNode in paragraphNode.iter(f"{{{self.namespaceMain}}}r"):
                size = sizeDefault
                length = 0

                sizeNode = runNode.find(f"{{{self.namespaceMain}}}rPr/{{{self.namespaceMain}}}sz")

                if sizeNode is not None and self.office._xmlNodeValue(sizeNode, self.namespaceMain) != "":
                    size = float(self.office._xmlNodeValue(sizeNode, self.namespaceMain))

                for node in runNode.iter(f"{{{self.namespaceMain}}}t"):
                    if node.text is not None:
                        length += len(node.text)

                if length > 0:
                    countObject[size] = countObject.get(size, 0) + length

            return self._sizeDominant(countObject)

        def _sizeDominant(self, countObject):
            result = 0.0
            countMax = 0

            for size in countObject:
                if countObject[size] > countMax:
                    countMax = countObject[size]
                    result = size

            return result

        def _paragraphNumberingCheck(self, paragraphNode, style, styleObject):
            numberingNode = paragraphNode.find(f"{{{self.namespaceMain}}}pPr/{{{self.namespaceMain}}}numPr/{{{self.namespaceMain}}}numId")

            if numberingNode is not None:
                return self.office._xmlNodeValue(numberingNode, self.namespaceMain) != self.valueNumberingNone

            styleVisitedList = []

            while style in styleObject and style not in styleVisitedList:
                if styleObject[style]["numbering"] != "":
                    return styleObject[style]["numbering"] != self.valueNumberingNone

                styleVisitedList.append(style)

                style = styleObject[style]["based"]

            return False

        def _paragraphDrawingCollect(self, paragraphNode):
            resultList = []

            for node in paragraphNode.iter():
                if self.office._xmlNodeTag(node) != "drawing":
                    continue

                chartNode = node.find(f".//{{{self.office.namespaceChart}}}chart")

                if chartNode is not None:
                    resultList.append({"kind": "image", "relationshipId": chartNode.attrib.get(f"{{{self.office.namespaceRelationship}}}id", ""), "isChart": True})

                    continue

                blipNode = node.find(f".//{{{self.office.namespaceDrawing}}}blip")

                if blipNode is not None:
                    resultList.append({"kind": "image", "relationshipId": blipNode.attrib.get(f"{{{self.office.namespaceRelationship}}}embed", ""), "isChart": False})

            return resultList

        def _tableDirection(self, tableNode):
            isVertical = False
            isRightToLeft = False

            for node in tableNode:
                if self.office._xmlNodeTag(node) != "tblPr":
                    continue

                for propertyNode in node:
                    tag = self.office._xmlNodeTag(propertyNode)

                    if tag == "bidiVisual" and propertyNode.attrib.get(f"{{{self.namespaceMain}}}val", "1") not in self.office.valueFalseList:
                        isRightToLeft = True
                    elif tag == "textDirection" and propertyNode.attrib.get(f"{{{self.namespaceMain}}}val", "")[0:4] == self.valueTextDirectionVertical:
                        isVertical = True

            return {"isVertical": isVertical, "isRightToLeft": isRightToLeft}

        def _blockWrapped(self, containerNode, styleObject, sizeDocument):
            blockList = []

            for node in containerNode:
                tag = self.office._xmlNodeTag(node)

                childList = []

                if tag == "p":
                    childList = self._blockParagraph(node, styleObject, True, sizeDocument)
                elif tag == "tbl":
                    childList = self._blockTable(node, styleObject, sizeDocument)

                for a in range(len(childList)):
                    blockList.append(childList[a])

            resultList = []

            for a in range(len(blockList)):
                block = blockList[a]

                isMerge = False

                if block["kind"] == "paragraph" and block["isWrapped"] and len(resultList) > 0:
                    previous = resultList[len(resultList) - 1]

                    if previous["kind"] == "paragraph" and previous["isWrapped"]:
                        isMerge = True

                        separator = "" if spacelessCheck(previous["text"][-1:]) and spacelessCheck(block["text"][0:1]) else " "

                        previous["text"] = f"{previous['text']}{separator}{block['text']}"

                if isMerge == False:
                    resultList.append(block)

            for a in range(len(resultList)):
                if resultList[a]["kind"] == "paragraph" and resultList[a]["isWrapped"]:
                    resultList[a]["isAside"] = len(resultList[a]["text"]) <= self.levelAsideLength

            return resultList

        def _blockTable(self, tableNode, styleObject, sizeDocument):
            resultList = []

            directionObject = self._tableDirection(tableNode)

            rowNodeList = []

            for node in tableNode:
                if self.office._xmlNodeTag(node) == "tr":
                    rowNodeList.append(node)

            columnMax = 0
            isData = len(rowNodeList) >= 2

            rowCellList = []
            openObject = {}

            for a in range(len(rowNodeList)):
                cellNodeList = []

                for node in rowNodeList[a]:
                    if self.office._xmlNodeTag(node) == "tc":
                        cellNodeList.append(node)

                cellList = []
                columnIndex = 0

                for b in range(len(cellNodeList)):
                    textList = []

                    for node in cellNodeList[b]:
                        tag = self.office._xmlNodeTag(node)

                        if tag == "p":
                            text = self.office._paragraphText(node, self.characterObject, self.tagSkipText)

                            if len(text) > 0:
                                textList.append(text)

                                if len(text) > self.levelAsideLength:
                                    isData = False
                        elif tag == "tbl":
                            isData = False

                    if len(self._paragraphDrawingCollect(cellNodeList[b])) > 0:
                        isData = False

                    columnSpan = self._cellColumnSpan(cellNodeList[b])

                    if self._cellMergeVertical(cellNodeList[b]) == "continue" and columnIndex in openObject:
                        openObject[columnIndex]["rowSpan"] += 1
                    else:
                        cellObject = {"text": " ".join(textList), "rowSpan": 1, "columnSpan": columnSpan}

                        cellList.append(cellObject)

                        openObject[columnIndex] = cellObject

                    columnIndex += columnSpan

                columnMax = max(columnMax, columnIndex)

                rowCellList.append(cellList)

            if columnMax < 2:
                isData = False

            if isData:
                isHeader = rowNodeList[0].find(f"{{{self.namespaceMain}}}trPr/{{{self.namespaceMain}}}tblHeader") is not None or self._rowBoldCheck(rowNodeList)

                for a in range(len(rowCellList)):
                    resultList.append({"kind": "tableRow", "cellList": rowCellList[a], "direction": directionObject, "isHeader": isHeader})
            else:
                for a in range(len(rowNodeList)):
                    for node in rowNodeList[a]:
                        if self.office._xmlNodeTag(node) == "tc":
                            blockList = self._blockWrapped(node, styleObject, sizeDocument)

                            for b in range(len(blockList)):
                                resultList.append(blockList[b])

            return resultList

        def _rowBoldCheck(self, rowNodeList):
            countObject = self._runBoldCount(rowNodeList[0])

            if countObject["count"] == 0 or countObject["countBold"] != countObject["count"]:
                return False

            count = 0
            countBold = 0

            for a in range(1, len(rowNodeList)):
                countRowObject = self._runBoldCount(rowNodeList[a])

                count += countRowObject["count"]
                countBold += countRowObject["countBold"]

            return count > 0 and countBold * 2 < count

        def _runBoldCount(self, rowNode):
            resultObject = {"count": 0, "countBold": 0}

            for runNode in rowNode.iter(f"{{{self.namespaceMain}}}r"):
                if runNode.find(f"{{{self.namespaceMain}}}t") is None:
                    continue

                resultObject["count"] += 1

                boldNode = runNode.find(f"{{{self.namespaceMain}}}rPr/{{{self.namespaceMain}}}b")

                if boldNode is not None and self.office._xmlNodeValue(boldNode, self.namespaceMain) not in self.office.valueFalseList:
                    resultObject["countBold"] += 1

            return resultObject

        def _cellColumnSpan(self, cellNode):
            value = self._cellPropertyValue(cellNode, "gridSpan")

            if value is None or value == "":
                return 1

            return int(value)

        def _cellPropertyValue(self, cellNode, tagProperty):
            result = None

            for node in cellNode:
                if self.office._xmlNodeTag(node) == "tcPr":
                    for nodeProperty in node:
                        if self.office._xmlNodeTag(nodeProperty) == tagProperty:
                            result = self.office._xmlNodeValue(nodeProperty, self.namespaceMain)

            return result

        def _cellMergeVertical(self, cellNode):
            value = self._cellPropertyValue(cellNode, "vMerge")

            if value is None:
                return ""

            return value if value != "" else "continue"

        def _asideMark(self, blockList):
            runIndexList = []

            for a in range(len(blockList)):
                block = blockList[a]

                isBreak = True

                if block["kind"] == "image":
                    isBreak = False
                elif block["kind"] == "paragraph":
                    if block["isAside"]:
                        isBreak = False
                    elif self._bodyTextCheck(block) and len(block["text"]) <= self.levelAsideLength:
                        if len(runIndexList) == 0 and self._continuationCheck(blockList[a - 1] if a > 0 else None, block):
                            block["isContinuation"] = True
                        else:
                            runIndexList.append(a)

                            isBreak = False

                if isBreak:
                    self._asideRunFlush(runIndexList, blockList)

                    runIndexList = []

            self._asideRunFlush(runIndexList, blockList)

            return blockList

        def _bodyTextCheck(self, block):
            result = False

            if block["kind"] == "paragraph" and block["outlineLevel"] == -1 and block["isList"] == False:
                if self._styleCheck(block, self.styleTitleList) == False and self._styleHeadingLevel(block) < 0:
                    if self._styleCheck(block, self.styleCaptionList) == False:
                        result = True

            return result

        def _styleCheck(self, block, styleNameList):
            return textNormalize(block["style"]) in styleNameList or textNormalize(block["styleName"]) in styleNameList

        def _styleHeadingLevel(self, block):
            match = re.match(self.patternStyleHeading, textNormalize(block["style"]))

            if match is None:
                match = re.match(self.patternStyleHeading, textNormalize(block["styleName"]))

            return int(match.group(1)) if match is not None else -1

        def _continuationCheck(self, previous, block):
            result = False

            if previous is not None and previous["kind"] == "paragraph" and previous["isAside"] == False:
                if len(previous["text"]) > self.levelAsideLength and previous["size"] == block["size"]:
                    if sentenceEndCheck(previous["text"], self.levelReferenceLength) == False:
                        result = True

            return result

        def _sentenceStartCheck(self, text):
            character = text[0:1]

            if icu.Char.hasBinaryProperty(character, icu.UProperty.CASED) == False:
                return False

            return icu.Char.hasBinaryProperty(character, icu.UProperty.LOWERCASE) == False

        def _asideRunFlush(self, runIndexList, blockList):
            if len(runIndexList) >= self.levelAsideCount:
                for a in range(len(runIndexList)):
                    blockList[runIndexList[a]]["isAside"] = True

        def _continuationMark(self, blockList):
            for a in range(len(blockList)):
                block = blockList[a]

                if block["kind"] == "paragraph" and block["isAside"] == False and block["isContinuation"] == False and self._bodyTextCheck(block):
                    isChained = False

                    if block["isWrapped"]:
                        previousBlock = self._previousBlock(a, blockList)

                        if previousBlock is not None and previousBlock["isAside"] and previousBlock["size"] == block["size"]:
                            if sentenceEndCheck(previousBlock["text"], self.levelReferenceLength) == False:
                                block["isAside"] = True

                                isChained = True

                    if isChained == False and (len(block["text"]) <= self.levelAsideLength or self._sentenceStartCheck(block["text"]) == False):
                        previous = self._previousParagraph(a, blockList)

                        if self._continuationCheck(previous, block):
                            block["isContinuation"] = True

            return blockList

        def _previousBlock(self, index, blockList):
            result = None

            for a in range(index - 1, -1, -1):
                block = blockList[a]

                if block["kind"] == "image":
                    continue

                if block["kind"] == "paragraph":
                    result = block

                break

            return result

        def _previousParagraph(self, index, blockList):
            result = None

            for a in range(index - 1, -1, -1):
                block = blockList[a]

                if block["kind"] == "paragraph":
                    if block["isAside"] == False:
                        result = block

                        break
                elif block["kind"] != "image":
                    break

            return result

        def _bodySize(self, blockList):
            countObject = {}

            for a in range(len(blockList)):
                if blockList[a]["kind"] == "paragraph" and blockList[a]["isAside"] == False:
                    size = blockList[a]["size"]

                    countObject[size] = countObject.get(size, 0) + len(blockList[a]["text"])

            return self._sizeDominant(countObject)

        def _titleSizeRank(self, blockList, bodySize):
            resultList = []

            for a in range(len(blockList)):
                block = blockList[a]

                if self._bodyTextCheck(block) and block["isAside"] == False:
                    if bodySize > 0 and block["size"] >= bodySize * self.levelTitleSize and len(block["text"]) <= self.levelTitleLength:
                        if block["size"] not in resultList:
                            resultList.append(block["size"])

            resultList.sort(reverse=True)

            return resultList

        def _itemLabel(self, block, titleSizeList, isDocTitleFound):
            resultObject = {"label": "text", "level": 0}

            styleLevel = self._styleHeadingLevel(block)

            if self._styleCheck(block, self.styleTitleList):
                resultObject["label"] = "doc_title"
            elif self._styleCheck(block, self.styleCaptionList):
                resultObject["label"] = "figure_title"
            elif styleLevel >= 0:
                resultObject["label"] = "paragraph_title"
                resultObject["level"] = styleLevel + 1
            elif block["outlineLevel"] >= 0:
                resultObject["label"] = "paragraph_title"
                resultObject["level"] = block["outlineLevel"] + 2
            elif block["size"] in titleSizeList and len(block["text"]) <= self.levelTitleLength:
                index = titleSizeList.index(block["size"])

                if index == 0 and isDocTitleFound == False:
                    resultObject["label"] = "doc_title"
                else:
                    resultObject["label"] = "paragraph_title"
                    resultObject["level"] = max(2, 1 + index) if isDocTitleFound else 2 + index

            return resultObject

        def _tableNearCheck(self, index, blockList):
            if index > 0 and blockList[index - 1]["kind"] == "tableRow":
                return True

            return index + 1 < len(blockList) and blockList[index + 1]["kind"] == "tableRow"

        def _noteCollect(self, pathObject, zipFile, itemSecondaryList):
            for relationshipId in pathObject:
                typeLast = pathObject[relationshipId]["type"].split("/")[-1]

                if typeLast not in self.noteTypeObject:
                    continue

                noteRootNode = self.office._xmlRootBuild(pathObject[relationshipId]["path"], zipFile)

                if noteRootNode is None:
                    continue

                self._fallbackRemove(noteRootNode)

                for noteNode in noteRootNode:
                    if noteNode.attrib.get(f"{{{self.namespaceMain}}}type", "") in self.noteTypeSkipList:
                        continue

                    text = self._nodeText(noteNode)

                    if len(text) > 0:
                        itemSecondaryList.append({"label": "footnote", "text": f"[^{self.noteTypeObject[typeLast]}{noteNode.attrib.get(f'{{{self.namespaceMain}}}id', '')}]: {text}"})

        def _nodeText(self, containerNode):
            textList = []

            for node in containerNode.iter(f"{{{self.namespaceMain}}}p"):
                text = self.office._paragraphText(node, self.characterObject, self.tagSkipText)

                if len(text) > 0:
                    textList.append(text)

            return " ".join(textList)

        def _partCollect(self, pathObject, zipFile, itemSecondaryList):
            textList = []

            for relationshipId in pathObject:
                typeLast = pathObject[relationshipId]["type"].split("/")[-1]

                if typeLast not in self.partLabelList:
                    continue

                partRootNode = self.office._xmlRootBuild(pathObject[relationshipId]["path"], zipFile)

                if partRootNode is None:
                    continue

                self._fallbackRemove(partRootNode)

                text = self._nodeText(partRootNode)

                if len(text) == 0 or text in textList:
                    continue

                textList.append(text)

                itemSecondaryList.append({"label": typeLast, "text": text})

        def execute(self, pathInput, pathOutput):
            zipFile = zipfile.ZipFile(pathInput)

            rootNode = self.office._xmlRootBuild("word/document.xml", zipFile)

            sizeDocument = 22.0
            styleObject = {}

            styleRootNode = self.office._xmlRootBuild("word/styles.xml", zipFile)

            if styleRootNode is not None:
                styleObject = self._styleBuild(styleRootNode)

                sizeNode = styleRootNode.find(
                    f"{{{self.namespaceMain}}}docDefaults/{{{self.namespaceMain}}}rPrDefault/{{{self.namespaceMain}}}rPr/{{{self.namespaceMain}}}sz"
                )

                if sizeNode is not None and self.office._xmlNodeValue(sizeNode, self.namespaceMain) != "":
                    sizeDocument = float(self.office._xmlNodeValue(sizeNode, self.namespaceMain))

            pathObject = self.office._relationshipBuild("word/document.xml", zipFile)

            blockList = []

            if rootNode is not None:
                self._fallbackRemove(rootNode)
                self._noteMarkWrite(rootNode)

                bodyNode = rootNode.find(f"{{{self.namespaceMain}}}body")

                if bodyNode is not None:
                    blockList = self._blockBuild(bodyNode, styleObject, sizeDocument)

            blockList = self._asideMark(blockList)
            blockList = self._continuationMark(blockList)

            bodySize = self._bodySize(blockList)
            titleSizeList = self._titleSizeRank(blockList, bodySize)

            itemMainList = []
            itemSecondaryList = []

            isDocTitleFound = False

            for a in range(len(blockList)):
                block = blockList[a]

                if block["kind"] == "tableRow":
                    textList = []

                    for b in range(len(block["cellList"])):
                        textList.append(block["cellList"][b]["text"])

                    itemMainList.append({"label": "tableRow", "text": " | ".join(textList), "cellList": block["cellList"], "direction": block["direction"], "isHeader": block["isHeader"]})
                elif block["kind"] == "image":
                    item = {"label": "image", "text": ""}

                    pathTarget = pathObject[block["relationshipId"]]["path"] if block["relationshipId"] in pathObject else ""

                    if block["isChart"]:
                        item["label"] = "chart"

                        chartRootNode = self.office._xmlRootBuild(pathTarget, zipFile)

                        if chartRootNode is not None:
                            item["text"] = self.office._xmlChartText(chartRootNode)
                    elif pathTarget in zipFile.namelist():
                        item["path"] = self.office._mediaWrite(zipFile, pathTarget, pathOutput)

                    itemSecondaryList.append(item)
                elif block["isAside"]:
                    itemSecondaryList.append({"label": "aside_text", "text": block["text"]})
                elif block["isContinuation"] and len(itemMainList) > 0:
                    itemPrevious = itemMainList[len(itemMainList) - 1]

                    if spacelessCheck(itemPrevious["text"][-1:]) and spacelessCheck(block["text"][0:1]):
                        itemPrevious["text"] += block["text"]
                    else:
                        itemPrevious["text"] += f" {block['text']}"
                else:
                    labelObject = self._itemLabel(block, titleSizeList, isDocTitleFound)

                    if labelObject["label"] == "doc_title":
                        isDocTitleFound = True

                    item = {"label": labelObject["label"], "text": block["text"]}

                    if labelObject["label"] == "paragraph_title":
                        item["level"] = labelObject["level"]

                    if labelObject["label"] == "text" and block["isList"]:
                        item["isList"] = True

                    if labelObject["label"] == "figure_title" and self._tableNearCheck(a, blockList) == False:
                        itemSecondaryList.append(item)
                    else:
                        itemMainList.append(item)

            self._noteCollect(pathObject, zipFile, itemSecondaryList)

            self._partCollect(pathObject, zipFile, itemSecondaryList)

            zipFile.close()

            self.office._flowAssign(itemMainList, itemSecondaryList)

            pageList = [{"number": 1, "itemMainList": itemMainList, "itemSecondaryList": itemSecondaryList}]

            if self.office.isDebug:
                astWrite(pathOutput, pageList)

            return {"pageList": pageList}

        def __init__(self, office):
            self.office = office

            self.namespaceMain = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

            self.characterObject = {"tab": "\t", "br": "\n", "cr": "\n", "noBreakHyphen": "-"}
            self.tagSkipText = "txbxContent"

            self.valueTextDirectionVertical = "tbRl"
            self.valueNumberingNone = "0"

            self.notePrefixObject = {"footnoteReference": "", "endnoteReference": "e", "commentReference": "c"}
            self.noteTypeObject = {"footnotes": "", "endnotes": "e", "comments": "c"}
            self.noteTypeSkipList = ["separator", "continuationSeparator", "continuationNotice"]
            self.partLabelList = ["header", "footer"]

            self.styleTitleList = ["title"]
            self.styleCaptionList = ["caption"]

            self.patternStyleHeading = r"heading(\d)$"

            self.levelTitleSize = 1.15
            self.levelTitleLength = 120
            self.levelAsideLength = 60
            self.levelAsideCount = 4

            self.levelReferenceLength = 20

    class Xlsx:
        def _sharedStringBuild(self, sharedStringRootNode):
            resultList = []

            for node in sharedStringRootNode.iter(f"{{{self.namespaceMain}}}si"):
                resultList.append(self.office._textCollect(node, self.characterObject, self.tagSkipText))

            return resultList

        def _sheetDirection(self, sheetRootNode):
            isRightToLeft = False

            if sheetRootNode is not None:
                viewNode = sheetRootNode.find(f"{{{self.namespaceMain}}}sheetViews/{{{self.namespaceMain}}}sheetView")

                if viewNode is not None and viewNode.attrib.get("rightToLeft", "0") == "1":
                    isRightToLeft = True

            return {"isVertical": False, "isRightToLeft": isRightToLeft}

        def _styleFormatBuild(self, styleRootNode):
            resultObject = {"dateList": [], "formatObject": {}, "boldList": []}

            fontBoldList = self._fontBoldCollect(styleRootNode)

            numberFormatObject = dict(self.numberFormatObject)

            for node in styleRootNode.iter(f"{{{self.namespaceMain}}}numFmt"):
                numberFormatObject[int(node.attrib.get("numFmtId", "-1"))] = node.attrib.get("formatCode", "")

            cellFormatNode = styleRootNode.find(f"{{{self.namespaceMain}}}cellXfs")

            if cellFormatNode is not None:
                indexFormat = 0

                for node in cellFormatNode:
                    if self.office._xmlNodeTag(node) == "xf":
                        numberFormatId = int(node.attrib.get("numFmtId", "0"))

                        if int(node.attrib.get("fontId", "0")) in fontBoldList:
                            resultObject["boldList"].append(indexFormat)

                        isDate = numberFormatId in self.numberFormatDateList

                        if isDate == False and numberFormatId in numberFormatObject:
                            isDate = self._dateFormatCheck(numberFormatObject[numberFormatId])

                        if isDate:
                            resultObject["dateList"].append(indexFormat)
                        elif numberFormatId in numberFormatObject:
                            resultObject["formatObject"][indexFormat] = numberFormatObject[numberFormatId]

                        indexFormat += 1

            return resultObject

        def _fontBoldCollect(self, styleRootNode):
            resultList = []

            fontRootNode = styleRootNode.find(f"{{{self.namespaceMain}}}fonts")

            if fontRootNode is None:
                return resultList

            indexFont = 0

            for node in fontRootNode:
                boldNode = node.find(f"{{{self.namespaceMain}}}b")

                if boldNode is not None and boldNode.attrib.get("val", "1") not in self.office.valueFalseList:
                    resultList.append(indexFont)

                indexFont += 1

            return resultList

        def _dateFormatCheck(self, formatCode):
            formatClean = re.sub(self.patternFormatLiteral, "", formatCode).strip()

            if formatClean == "" or formatClean.casefold() == self.textFormatGeneral:
                return False

            if re.search(self.patternFormatNumber, formatClean) is not None:
                return False

            return self._letterCheck(formatClean)

        def _letterCheck(self, text):
            for a in range(len(text)):
                if icu.Char.isalpha(text[a]):
                    return True

            return False

        def _sheetBuild(self, zipFile):
            resultList = []

            workbookRootNode = self.office._xmlRootBuild("xl/workbook.xml", zipFile)

            pathObject = self.office._relationshipBuild("xl/workbook.xml", zipFile)

            if workbookRootNode is not None:
                for node in workbookRootNode.iter(f"{{{self.namespaceMain}}}sheet"):
                    relationshipId = node.attrib.get(f"{{{self.office.namespaceRelationship}}}id", "")

                    if relationshipId in pathObject and "worksheets/" in pathObject[relationshipId]["path"]:
                        resultList.append({"name": node.attrib.get("name", ""), "path": pathObject[relationshipId]["path"]})

            return resultList

        def _dateSystemCheck(self, zipFile):
            workbookRootNode = self.office._xmlRootBuild("xl/workbook.xml", zipFile)

            if workbookRootNode is None:
                return False

            propertyNode = workbookRootNode.find(f"{{{self.namespaceMain}}}workbookPr")

            if propertyNode is None:
                return False

            return propertyNode.attrib.get("date1904", "0") not in self.office.valueFalseList

        def _rowCollect(self, sheetRootNode, sharedStringList, styleFormatObject, isDate1904):
            rowObjectList = []

            rowNumberNext = 1

            for rowNode in sheetRootNode.iter(f"{{{self.namespaceMain}}}row"):
                rowNumberText = rowNode.attrib.get("r", "")
                rowNumber = int(rowNumberText) if rowNumberText.isdigit() else rowNumberNext

                cellList = []
                columnNext = 0
                isBold = True
                isText = False

                for cellNode in rowNode:
                    if self.office._xmlNodeTag(cellNode) == "c":
                        reference = cellNode.attrib.get("r", "")
                        column = self.office._gridColumnIndex(reference) if reference != "" else columnNext

                        while len(cellList) < column:
                            cellList.append("")

                        cellText = self._cellText(cellNode, sharedStringList, styleFormatObject, isDate1904)

                        cellList.append(cellText)

                        if cellText != "":
                            isText = True

                            styleText = cellNode.attrib.get("s", "")

                            if (int(styleText) if styleText.isdigit() else -1) not in styleFormatObject["boldList"]:
                                isBold = False

                        columnNext = column + 1

                while len(cellList) > 0 and cellList[len(cellList) - 1] == "":
                    cellList.pop()

                rowObjectList.append({"number": rowNumber, "cellList": cellList, "isBold": isBold and isText})

                rowNumberNext = rowNumber + 1

            numberFirst = 0
            numberLast = 0
            columnCount = 0

            for a in range(len(rowObjectList)):
                if len(rowObjectList[a]["cellList"]) > 0:
                    if numberFirst == 0:
                        numberFirst = rowObjectList[a]["number"]

                    numberLast = rowObjectList[a]["number"]
                    columnCount = max(columnCount, len(rowObjectList[a]["cellList"]))

            cellListObject = {}
            boldObject = {}

            for a in range(len(rowObjectList)):
                cellListObject[rowObjectList[a]["number"]] = rowObjectList[a]["cellList"]
                boldObject[rowObjectList[a]["number"]] = rowObjectList[a]["isBold"]

            resultList = []

            if numberFirst > 0:
                for a in range(numberFirst, numberLast + 1):
                    cellList = cellListObject[a] if a in cellListObject else []

                    while len(cellList) < columnCount:
                        cellList.append("")

                    resultList.append({"number": a, "cellList": cellList, "isBold": a in boldObject and boldObject[a]})

            return resultList

        def _cellText(self, cellNode, sharedStringList, styleFormatObject, isDate1904):
            result = ""

            cellType = cellNode.attrib.get("t", "n")

            valueNode = cellNode.find(f"{{{self.namespaceMain}}}v")
            valueText = valueNode.text if valueNode is not None and valueNode.text is not None else ""

            if cellType == "s":
                if valueText != "" and int(valueText) < len(sharedStringList):
                    result = sharedStringList[int(valueText)]
            elif cellType == "inlineStr":
                inlineNode = cellNode.find(f"{{{self.namespaceMain}}}is")

                if inlineNode is not None:
                    result = self.office._textCollect(inlineNode, self.characterObject, self.tagSkipText)
            elif cellType == "b":
                result = "TRUE" if valueText == "1" else "FALSE"
            elif cellType == "str" or cellType == "e":
                result = valueText
            else:
                result = valueText

                if valueText != "" and self._numberCheck(valueText):
                    styleText = cellNode.attrib.get("s", "")
                    styleIndex = int(styleText) if styleText.isdigit() else -1

                    if styleIndex in styleFormatObject["dateList"]:
                        result = self._dateText(isDate1904, float(valueText))
                    elif styleIndex in styleFormatObject["formatObject"]:
                        result = self._numberFormat(valueText, styleFormatObject["formatObject"][styleIndex])
                    else:
                        result = self._numberText(valueText)

            return result.strip()

        def _numberCheck(self, text):
            return re.match(r"^-?\d+(\.\d+)?([eE][+-]?\d+)?$", text) is not None

        def _dateText(self, isDate1904, value):
            dateValue = (datetime.datetime(1904, 1, 1) if isDate1904 else datetime.datetime(1899, 12, 30)) + datetime.timedelta(days=value)

            result = dateValue.strftime("%Y-%m-%d %H:%M:%S")

            if value < 1.0:
                result = dateValue.strftime("%H:%M:%S")
            elif value == int(value):
                result = dateValue.strftime("%Y-%m-%d")

            return result

        def _numberText(self, text):
            result = text

            value = float(text)

            if value == int(value):
                result = str(int(value))

            return result

        def _numberFormat(self, valueText, formatCode):
            value = decimal.Decimal(valueText)

            sectionList = re.findall(self.patternFormatSection, formatCode)

            sectionText = sectionList[0]
            isSign = value < 0

            if value < 0 and len(sectionList) > 1:
                sectionText = sectionList[1]
                isSign = False
            elif value == 0 and len(sectionList) > 2:
                sectionText = sectionList[2]

            tokenList = re.findall(self.patternFormatToken, sectionText)

            countDigit = 0
            countPercent = 0

            for a in range(len(tokenList)):
                if re.fullmatch(self.patternFormatDigit, tokenList[a]) is not None:
                    countDigit += 1
                elif tokenList[a] == "%":
                    countPercent += 1
                elif tokenList[a] in self.formatUnsupportedList:
                    return self._numberText(valueText)

            if countDigit > 1:
                return self._numberText(valueText)

            valueScaled = abs(value) * (decimal.Decimal(100) ** countPercent)

            result = "-" if isSign else ""

            for a in range(len(tokenList)):
                token = tokenList[a]

                if re.fullmatch(self.patternFormatDigit, token) is not None:
                    result += self._numberDigit(token, valueScaled)
                elif token[0:1] == "\"":
                    result += token[1:-1]
                elif token[0:1] == "\\":
                    result += token[1:]
                elif token[0:1] == "_":
                    result += " "
                elif token[0:2] == "[$":
                    result += token[2:-1].split("-")[0]
                elif token[0:1] != "*" and token[0:1] != "[":
                    result += token

            return result.strip()

        def _numberDigit(self, token, value):
            tokenScale = token.rstrip(",")

            valueScaled = value / (decimal.Decimal(1000) ** (len(token) - len(tokenScale)))

            partList = tokenScale.split(".")

            partDecimal = partList[1] if len(partList) > 1 else ""

            countZero = partDecimal.count("0")

            valueRounded = valueScaled.quantize(decimal.Decimal(1).scaleb(-len(partDecimal)), rounding=decimal.ROUND_HALF_UP)

            result = format(valueRounded, ",f") if "," in partList[0] else format(valueRounded, "f").zfill(partList[0].count("0") + len(partDecimal) + (1 if len(partDecimal) > 0 else 0))

            if len(partDecimal) > countZero:
                integerText, decimalText = result.split(".")

                while len(decimalText) > countZero and decimalText[-1:] == "0":
                    decimalText = decimalText[0:-1]

                result = f"{integerText}.{decimalText}" if len(decimalText) > 0 else integerText

            return result

        def _mergeCollect(self, sheetRootNode):
            resultList = []

            for node in sheetRootNode.iter(f"{{{self.namespaceMain}}}mergeCell"):
                reference = node.attrib.get("ref", "")

                if reference != "":
                    resultList.append(reference)

            return resultList

        def _drawingCollect(self, zipFile, sheetPath, pathOutput):
            resultList = []

            sheetPathObject = self.office._relationshipBuild(sheetPath, zipFile)

            for sheetRelationshipId in sheetPathObject:
                if sheetPathObject[sheetRelationshipId]["type"].endswith("/drawing") == False:
                    continue

                pathDrawing = sheetPathObject[sheetRelationshipId]["path"]

                drawingRootNode = self.office._xmlRootBuild(pathDrawing, zipFile)

                pathObject = self.office._relationshipBuild(pathDrawing, zipFile)

                if drawingRootNode is not None:
                    for drawingNode in drawingRootNode.iter():
                        tag = self.office._xmlNodeTag(drawingNode)

                        if tag == "graphicFrame":
                            chartNode = drawingNode.find(f".//{{{self.office.namespaceChart}}}chart")

                            if chartNode is not None:
                                item = {"label": "chart", "text": ""}

                                relationshipId = chartNode.attrib.get(f"{{{self.office.namespaceRelationship}}}id", "")
                                pathChart = pathObject[relationshipId]["path"] if relationshipId in pathObject else ""

                                chartRootNode = self.office._xmlRootBuild(pathChart, zipFile)

                                if chartRootNode is not None:
                                    item["text"] = self.office._xmlChartText(chartRootNode)

                                resultList.append(item)
                        elif tag == "pic":
                            blipNode = drawingNode.find(f".//{{{self.office.namespaceDrawing}}}blip")

                            if blipNode is not None:
                                item = {"label": "image", "text": ""}

                                relationshipId = blipNode.attrib.get(f"{{{self.office.namespaceRelationship}}}embed", "")
                                pathMedia = pathObject[relationshipId]["path"] if relationshipId in pathObject else ""

                                if pathMedia in zipFile.namelist():
                                    item["path"] = self.office._mediaWrite(zipFile, pathMedia, pathOutput)

                                resultList.append(item)

            return resultList

        def execute(self, pathInput, pathOutput):
            zipFile = zipfile.ZipFile(pathInput)

            sharedStringList = []
            styleFormatObject = {"dateList": [], "formatObject": {}, "boldList": []}

            sharedStringRootNode = self.office._xmlRootBuild("xl/sharedStrings.xml", zipFile)

            if sharedStringRootNode is not None:
                sharedStringList = self._sharedStringBuild(sharedStringRootNode)

            styleRootNode = self.office._xmlRootBuild("xl/styles.xml", zipFile)

            if styleRootNode is not None:
                styleFormatObject = self._styleFormatBuild(styleRootNode)

            sheetList = self._sheetBuild(zipFile)

            isDate1904 = self._dateSystemCheck(zipFile)

            pageList = []

            for a in range(len(sheetList)):
                sheetRootNode = self.office._xmlRootBuild(sheetList[a]["path"], zipFile)

                rowList = self._rowCollect(sheetRootNode, sharedStringList, styleFormatObject, isDate1904) if sheetRootNode is not None else []
                mergeList = self._mergeCollect(sheetRootNode) if sheetRootNode is not None else []

                directionObject = self._sheetDirection(sheetRootNode)

                itemMainList = [{"label": "sheetName", "text": sheetList[a]["name"]}]

                for b in range(len(rowList)):
                    itemMainList.append({"label": "tableRow", "number": rowList[b]["number"], "text": " | ".join(rowList[b]["cellList"]), "cellList": rowList[b]["cellList"], "isBold": rowList[b]["isBold"]})

                itemSecondaryList = self._drawingCollect(zipFile, sheetList[a]["path"], pathOutput)

                self.office._flowAssign(itemMainList, itemSecondaryList)

                pageList.append({"number": a + 1, "direction": directionObject, "mergeList": mergeList, "itemMainList": itemMainList, "itemSecondaryList": itemSecondaryList})

            zipFile.close()

            if self.office.isDebug:
                astWrite(pathOutput, pageList)

            return {"pageList": pageList}

        def __init__(self, office):
            self.office = office

            self.namespaceMain = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

            self.characterObject = {}
            self.tagSkipText = "rPh"

            self.numberFormatDateList = [14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47]

            self.numberFormatObject = {
                1: "0",
                2: "0.00",
                3: "#,##0",
                4: "#,##0.00",
                9: "0%",
                10: "0.00%",
                37: "#,##0 ;(#,##0)",
                38: "#,##0 ;(#,##0)",
                39: "#,##0.00;(#,##0.00)",
                40: "#,##0.00;(#,##0.00)"
            }

            self.patternFormatLiteral = r"\"[^\"]*\"|\[[^\]]*\]|\\."
            self.patternFormatNumber = r"[0#?]"
            self.patternFormatSection = r"(?:\"[^\"]*\"|\\.|[^;])+"
            self.patternFormatToken = r"\"[^\"]*\"|\\.|_.|\*.|\[[^\]]*\]|[0#?,.]*[0#?][0#?,.]*|."
            self.patternFormatDigit = r"[0#?,.]*[0#?][0#?,.]*"
            self.formatUnsupportedList = ["/", "E", "e", "@"]

            self.textFormatGeneral = "general"

    class Pptx:
        def _slideBuild(self, zipFile):
            resultList = []

            presentationRootNode = self.office._xmlRootBuild("ppt/presentation.xml", zipFile)

            pathObject = self.office._relationshipBuild("ppt/presentation.xml", zipFile)

            if presentationRootNode is not None:
                for node in presentationRootNode.iter(f"{{{self.namespaceMain}}}sldId"):
                    relationshipId = node.attrib.get(f"{{{self.office.namespaceRelationship}}}id", "")

                    if relationshipId in pathObject:
                        resultList.append(pathObject[relationshipId]["path"])

            return resultList

        def _placeholderBuild(self, pathObject, zipFile):
            resultObject = {"layout": {}, "master": {}}

            for relationshipId in pathObject:
                if pathObject[relationshipId]["type"].endswith("/slideLayout") == False:
                    continue

                pathLayout = pathObject[relationshipId]["path"]

                self._placeholderCollect(self.office._xmlRootBuild(pathLayout, zipFile), resultObject["layout"])

                pathLayoutObject = self.office._relationshipBuild(pathLayout, zipFile)

                for relationshipLayoutId in pathLayoutObject:
                    if pathLayoutObject[relationshipLayoutId]["type"].endswith("/slideMaster"):
                        self._placeholderCollect(self.office._xmlRootBuild(pathLayoutObject[relationshipLayoutId]["path"], zipFile), resultObject["master"])

            return resultObject

        def _placeholderCollect(self, rootNode, resultObject):
            if rootNode is None:
                return

            for shapeNode in rootNode.iter(f"{{{self.namespaceMain}}}sp"):
                placeholderNode = shapeNode.find(f"{{{self.namespaceMain}}}nvSpPr/{{{self.namespaceMain}}}nvPr/{{{self.namespaceMain}}}ph")

                if placeholderNode is None:
                    continue

                detailObject = {
                    "bbox": self._xfrmBox(shapeNode.find(f"{{{self.namespaceMain}}}spPr/{{{self.office.namespaceDrawing}}}xfrm"), None),
                    "isBulletNone": shapeNode.find(f".//{{{self.office.namespaceDrawing}}}lvl1pPr/{{{self.office.namespaceDrawing}}}buNone") is not None
                }

                if "idx" in placeholderNode.attrib:
                    resultObject[f"idx{placeholderNode.attrib['idx']}"] = detailObject

                resultObject[f"type{placeholderNode.attrib.get('type', 'body')}"] = detailObject

        def _xfrmBox(self, transformNode, transformObject):
            if transformNode is None:
                return None

            offsetNode = transformNode.find(f"{{{self.office.namespaceDrawing}}}off")
            extentNode = transformNode.find(f"{{{self.office.namespaceDrawing}}}ext")

            if offsetNode is None or extentNode is None:
                return None

            x1 = int(offsetNode.attrib.get("x", "0"))
            y1 = int(offsetNode.attrib.get("y", "0"))
            x2 = x1 + int(extentNode.attrib.get("cx", "0"))
            y2 = y1 + int(extentNode.attrib.get("cy", "0"))

            if transformObject is None:
                return [x1, y1, x2, y2]

            return [
                transformObject["offsetX"] + (x1 - transformObject["childX"]) * transformObject["scaleX"],
                transformObject["offsetY"] + (y1 - transformObject["childY"]) * transformObject["scaleY"],
                transformObject["offsetX"] + (x2 - transformObject["childX"]) * transformObject["scaleX"],
                transformObject["offsetY"] + (y2 - transformObject["childY"]) * transformObject["scaleY"]
            ]

        def _shapeBuild(self, containerNode, transformObject, placeholderObject):
            resultList = []

            for node in containerNode:
                tag = self.office._xmlNodeTag(node)

                if tag == "sp":
                    shapeObject = self._shapeText(node, transformObject, placeholderObject)

                    if len(shapeObject["blockList"]) > 0:
                        resultList.append(shapeObject)
                elif tag == "graphicFrame":
                    chartNode = node.find(f".//{{{self.office.namespaceChart}}}chart")
                    tableNode = node.find(f".//{{{self.office.namespaceDrawing}}}tbl")

                    blockList = []

                    if chartNode is not None:
                        blockList = [{"kind": "chart", "relationshipId": chartNode.attrib.get(f"{{{self.office.namespaceRelationship}}}id", "")}]
                    elif tableNode is not None:
                        blockList = self._blockTable(tableNode)

                    if len(blockList) > 0:
                        resultList.append({"bbox": self._xfrmBox(node.find(f"{{{self.namespaceMain}}}xfrm"), transformObject), "blockList": blockList, "isCell": False})
                elif tag == "pic":
                    blipNode = node.find(f".//{{{self.office.namespaceDrawing}}}blip")

                    if blipNode is not None:
                        resultList.append({
                            "bbox": self._xfrmBox(node.find(f"{{{self.namespaceMain}}}spPr/{{{self.office.namespaceDrawing}}}xfrm"), transformObject),
                            "blockList": [{"kind": "image", "relationshipId": blipNode.attrib.get(f"{{{self.office.namespaceRelationship}}}embed", "")}],
                            "isCell": False
                        })
                elif tag == "grpSp":
                    resultList = resultList + self._shapeBuild(node, self._groupTransform(node, transformObject), placeholderObject)

            return resultList

        def _shapeText(self, shapeNode, transformObject, placeholderObject):
            blockList = []

            placeholderType = self._placeholderType(shapeNode)

            bboxList = self._xfrmBox(shapeNode.find(f"{{{self.namespaceMain}}}spPr/{{{self.office.namespaceDrawing}}}xfrm"), transformObject)

            detailObject = self._placeholderDetail(shapeNode, placeholderObject)

            if bboxList is None and detailObject is not None:
                bboxList = detailObject["bbox"]

            isBullet = placeholderType in self.placeholderBulletList and (detailObject is None or detailObject["isBulletNone"] == False)

            if placeholderType in self.placeholderSkipList:
                return {"bbox": bboxList, "blockList": blockList, "isCell": False}

            textBodyNode = shapeNode.find(f"{{{self.namespaceMain}}}txBody")

            if textBodyNode is not None:
                for paragraphNode in textBodyNode:
                    if self.office._xmlNodeTag(paragraphNode) != "p":
                        continue

                    text = self.office._paragraphText(paragraphNode, self.characterObject, self.tagSkipText)

                    if len(text) > 0:
                        blockList.append({"kind": "paragraph", "text": text, "placeholderType": placeholderType, "isList": self._paragraphListCheck(paragraphNode, isBullet)})

            isCell = len(blockList) == 1 and blockList[0]["isList"] == False and len(blockList[0]["text"]) <= self.levelCellLength and placeholderType not in self.placeholderTitleList

            return {"bbox": bboxList, "blockList": blockList, "isCell": isCell}

        def _placeholderDetail(self, shapeNode, placeholderObject):
            placeholderNode = shapeNode.find(f"{{{self.namespaceMain}}}nvSpPr/{{{self.namespaceMain}}}nvPr/{{{self.namespaceMain}}}ph")

            if placeholderNode is None:
                return None

            placeholderType = placeholderNode.attrib.get("type", "body")

            keyList = [f"idx{placeholderNode.attrib.get('idx', '')}", f"type{placeholderType}"]

            for a in range(len(keyList)):
                if keyList[a] in placeholderObject["layout"]:
                    return placeholderObject["layout"][keyList[a]]

            keyMaster = f"type{self.placeholderMasterObject[placeholderType]}" if placeholderType in self.placeholderMasterObject else f"type{placeholderType}"

            return placeholderObject["master"][keyMaster] if keyMaster in placeholderObject["master"] else None

        def _paragraphListCheck(self, paragraphNode, isBullet):
            propertyNode = paragraphNode.find(f"{{{self.office.namespaceDrawing}}}pPr")

            if propertyNode is not None:
                if propertyNode.find(f"{{{self.office.namespaceDrawing}}}buNone") is not None:
                    return False

                if propertyNode.find(f"{{{self.office.namespaceDrawing}}}buChar") is not None or propertyNode.find(f"{{{self.office.namespaceDrawing}}}buAutoNum") is not None:
                    return True

            return isBullet

        def _groupTransform(self, groupNode, transformObject):
            transformNode = groupNode.find(f"{{{self.namespaceMain}}}grpSpPr/{{{self.office.namespaceDrawing}}}xfrm")

            if transformNode is None:
                return transformObject

            bboxList = self._xfrmBox(transformNode, transformObject)

            childOffsetNode = transformNode.find(f"{{{self.office.namespaceDrawing}}}chOff")
            childExtentNode = transformNode.find(f"{{{self.office.namespaceDrawing}}}chExt")

            if bboxList is None or childOffsetNode is None or childExtentNode is None:
                return transformObject

            childWidth = int(childExtentNode.attrib.get("cx", "0"))
            childHeight = int(childExtentNode.attrib.get("cy", "0"))

            return {
                "offsetX": bboxList[0],
                "offsetY": bboxList[1],
                "childX": int(childOffsetNode.attrib.get("x", "0")),
                "childY": int(childOffsetNode.attrib.get("y", "0")),
                "scaleX": (bboxList[2] - bboxList[0]) / childWidth if childWidth > 0 else 1,
                "scaleY": (bboxList[3] - bboxList[1]) / childHeight if childHeight > 0 else 1
            }

        def _blockOrder(self, shapeList):
            resultList = []

            shapeNoneList = []
            shapeSortedList = []

            for a in range(len(shapeList)):
                if shapeList[a]["bbox"] is None:
                    shapeNoneList.append(shapeList[a])
                else:
                    shapeSortedList.append(shapeList[a])

            shapeSortedList.sort(key=lambda shapeObject: shapeObject["bbox"][1])

            bandList = []

            for a in range(len(shapeSortedList)):
                bboxList = shapeSortedList[a]["bbox"]

                isAdded = False

                for b in range(len(bandList)):
                    if rangeOverlapRatio(bboxList[1], bboxList[3], bandList[b]["y1"], bandList[b]["y2"]) < self.levelBandOverlap:
                        continue

                    bandList[b]["y1"] = min(bandList[b]["y1"], bboxList[1])
                    bandList[b]["y2"] = max(bandList[b]["y2"], bboxList[3])

                    bandList[b]["shapeList"].append(shapeSortedList[a])

                    isAdded = True

                    break

                if isAdded == False:
                    bandList.append({"y1": bboxList[1], "y2": bboxList[3], "shapeList": [shapeSortedList[a]]})

            bandList.sort(key=lambda bandObject: bandObject["y1"])

            for a in range(len(shapeNoneList)):
                resultList = resultList + shapeNoneList[a]["blockList"]

            for a in range(len(bandList)):
                resultList = resultList + self._bandBlockBuild(bandList[a]["shapeList"])

            return resultList

        def _bandBlockBuild(self, shapeList):
            shapeSortedList = sorted(shapeList, key=lambda shapeObject: (shapeObject["bbox"][0], shapeObject["bbox"][1]))

            isRow = len(shapeSortedList) > 1

            for a in range(len(shapeSortedList)):
                if shapeSortedList[a]["isCell"] == False:
                    isRow = False

            resultList = []

            if isRow:
                cellList = []

                for a in range(len(shapeSortedList)):
                    cellList.append({"text": shapeSortedList[a]["blockList"][0]["text"], "rowSpan": 1, "columnSpan": 1})

                return [{"kind": "tableRow", "cellList": cellList, "direction": {"isVertical": False, "isRightToLeft": False}, "isHeader": False}]

            for a in range(len(shapeSortedList)):
                resultList = resultList + shapeSortedList[a]["blockList"]

            return resultList

        def _placeholderType(self, shapeNode):
            result = ""

            placeholderNode = shapeNode.find(f"{{{self.namespaceMain}}}nvSpPr/{{{self.namespaceMain}}}nvPr/{{{self.namespaceMain}}}ph")

            if placeholderNode is not None:
                result = placeholderNode.attrib.get("type", "body")

            return result

        def _blockTable(self, tableNode):
            resultList = []

            directionObject = self._tableDirection(tableNode)

            isHeader = self._tableHeaderCheck(tableNode)

            for rowNode in tableNode:
                if self.office._xmlNodeTag(rowNode) == "tr":
                    cellList = []

                    for cellNode in rowNode:
                        if self.office._xmlNodeTag(cellNode) == "tc":
                            if cellNode.attrib.get("hMerge", "") == "1" or cellNode.attrib.get("vMerge", "") == "1":
                                continue

                            textList = []

                            for paragraphNode in cellNode.iter(f"{{{self.office.namespaceDrawing}}}p"):
                                text = self.office._paragraphText(paragraphNode, self.characterObject, self.tagSkipText)

                                if len(text) > 0:
                                    textList.append(text)

                            cellList.append({
                                "text": " ".join(textList),
                                "rowSpan": int(cellNode.attrib.get("rowSpan", "1")),
                                "columnSpan": int(cellNode.attrib.get("gridSpan", "1"))
                            })

                    resultList.append({"kind": "tableRow", "cellList": cellList, "direction": directionObject, "isHeader": isHeader})

            return resultList

        def _tableHeaderCheck(self, tableNode):
            for node in tableNode:
                if self.office._xmlNodeTag(node) == "tblPr":
                    return node.attrib.get("firstRow", "0") == "1"

            return False

        def _tableDirection(self, tableNode):
            isRightToLeft = False

            for node in tableNode:
                if self.office._xmlNodeTag(node) == "tblPr" and node.attrib.get("rtl", "0") == "1":
                    isRightToLeft = True

            return {"isVertical": False, "isRightToLeft": isRightToLeft}

        def _notesText(self, pathObject, zipFile):
            result = ""

            for relationshipId in pathObject:
                if pathObject[relationshipId]["type"].endswith("/notesSlide"):
                    notesRootNode = self.office._xmlRootBuild(pathObject[relationshipId]["path"], zipFile)

                    if notesRootNode is not None:
                        textList = []

                        for shapeNode in notesRootNode.iter(f"{{{self.namespaceMain}}}sp"):
                            if self._placeholderType(shapeNode) == "body":
                                for paragraphNode in shapeNode.iter(f"{{{self.office.namespaceDrawing}}}p"):
                                    text = self.office._paragraphText(paragraphNode, self.characterObject, self.tagSkipText)

                                    if len(text) > 0:
                                        textList.append(text)

                        result = "\n".join(textList)

            return result

        def execute(self, pathInput, pathOutput):
            zipFile = zipfile.ZipFile(pathInput)

            slidePathList = self._slideBuild(zipFile)

            pageList = []

            isDocTitleFound = False

            for a in range(len(slidePathList)):
                slideRootNode = self.office._xmlRootBuild(slidePathList[a], zipFile)

                pathObject = self.office._relationshipBuild(slidePathList[a], zipFile)

                blockList = []

                if slideRootNode is not None:
                    treeNode = slideRootNode.find(f"{{{self.namespaceMain}}}cSld/{{{self.namespaceMain}}}spTree")

                    if treeNode is not None:
                        blockList = self._blockOrder(self._shapeBuild(treeNode, None, self._placeholderBuild(pathObject, zipFile)))

                itemMainList = [{"label": "slideNumber", "text": f"[Slide {a + 1}]"}]
                itemSecondaryList = []

                for b in range(len(blockList)):
                    block = blockList[b]

                    if block["kind"] == "paragraph":
                        if block["placeholderType"] == "title" or block["placeholderType"] == "ctrTitle":
                            if isDocTitleFound == False:
                                isDocTitleFound = True

                                itemMainList.append({"label": "doc_title", "text": block["text"]})
                            else:
                                itemMainList.append({"label": "paragraph_title", "level": 2, "text": block["text"]})
                        else:
                            itemMainList.append({"label": "text", "text": block["text"], "isList": block["isList"]})
                    elif block["kind"] == "tableRow":
                        textList = []

                        for c in range(len(block["cellList"])):
                            textList.append(block["cellList"][c]["text"])

                        itemMainList.append({"label": "tableRow", "text": " | ".join(textList), "cellList": block["cellList"], "direction": block["direction"], "isHeader": block["isHeader"]})
                    elif block["kind"] == "chart":
                        item = {"label": "chart", "text": ""}

                        pathChart = pathObject[block["relationshipId"]]["path"] if block["relationshipId"] in pathObject else ""

                        chartRootNode = self.office._xmlRootBuild(pathChart, zipFile)

                        if chartRootNode is not None:
                            item["text"] = self.office._xmlChartText(chartRootNode)

                        itemSecondaryList.append(item)
                    elif block["kind"] == "image":
                        item = {"label": "image", "text": ""}

                        pathMedia = pathObject[block["relationshipId"]]["path"] if block["relationshipId"] in pathObject else ""

                        if pathMedia in zipFile.namelist():
                            item["path"] = self.office._mediaWrite(zipFile, pathMedia, pathOutput)

                        itemSecondaryList.append(item)

                notesText = self._notesText(pathObject, zipFile)

                if len(notesText) > 0:
                    itemSecondaryList.append({"label": "aside_text", "text": notesText})

                self.office._flowAssign(itemMainList, itemSecondaryList)

                pageList.append({"number": a + 1, "itemMainList": itemMainList, "itemSecondaryList": itemSecondaryList})

            zipFile.close()

            if self.office.isDebug:
                astWrite(pathOutput, pageList)

            return {"pageList": pageList}

        def __init__(self, office):
            self.office = office

            self.namespaceMain = "http://schemas.openxmlformats.org/presentationml/2006/main"

            self.characterObject = {"tab": "\t", "br": "\n"}
            self.tagSkipText = ""

            self.placeholderSkipList = ["sldNum", "dt", "ftr"]
            self.placeholderBulletList = ["body", "obj"]
            self.placeholderTitleList = ["title", "ctrTitle", "subTitle"]
            self.placeholderMasterObject = {"ctrTitle": "title", "subTitle": "body", "obj": "body"}

            self.levelCellLength = 60
            self.levelBandOverlap = 0.5
