import sys
import re
import decimal
import zipfile
import datetime
import unicodedata
import icu

sys.dont_write_bytecode = True

# Source
from helper import numberText, patternNumber, symbolText, symbolObject, noteMark, noteText, markComment, drawingSymbolWrite, xmlRootBuild, xmlNodeTag, xmlTextCollect, xmlRelationshipBuild, xmlRelationshipNodeList, xmlFallbackRemove, xmlChartItemList, xmlParagraphText, gridRowList, labelText, labelTable, labelTitle, namespaceDrawing, namespaceChart, namespaceRelationship, characterDrawingObject, valueFalseList

class Xlsx:
    def _symbolWrite(self, stringNode):
        for runNode in stringNode.iter(f"{{{self.namespace}}}r"):
            fontNode = runNode.find(f"{{{self.namespace}}}rPr/{{{self.namespace}}}rFont")

            font = fontNode.attrib.get("val", "").casefold() if fontNode is not None else ""

            for node in runNode:
                if xmlNodeTag(node) == "t" and font in symbolObject and node.text is not None:
                    node.text = symbolText(node.text, font)

    def _stringObject(self, stringNode):
        self._symbolWrite(stringNode)

        return {"text": xmlTextCollect(stringNode, {}, self.tagSkip), "isPlain": stringNode.find(f"{{{self.namespace}}}r") is None}

    def _sharedStringBuild(self, sharedStringRootNode):
        return [self._stringObject(node) for node in sharedStringRootNode.iter(f"{{{self.namespace}}}si")]

    def _dateFormatCheck(self, formatCode):
        formatClean = re.sub(self.patternFormatSecondFraction, "", re.sub(self.patternFormatLiteral, "", formatCode)).strip()

        if formatClean == "" or formatClean.casefold() == self.textFormatGeneral or re.search(self.patternFormatNumber, formatClean) is not None:
            return False

        return len([character for character in formatClean if unicodedata.category(character)[0] == "L"]) > 0

    def _styleFormatBuild(self, styleRootNode):
        resultObject = {"dateObject": {}, "formatObject": {}, "fontObject": {}}

        numberFormatObject = dict(self.numberFormatObject)
        numberFormatDateObject = dict(self.numberFormatDateObject)

        fontListNode = styleRootNode.find(f"{{{self.namespace}}}fonts")

        fontNodeList = [node for node in fontListNode if xmlNodeTag(node) == "font"] if fontListNode is not None else []

        fontNameList = []

        for a in range(len(fontNodeList)):
            nameNode = fontNodeList[a].find(f"{{{self.namespace}}}name")

            fontNameList.append(nameNode.attrib.get("val", "").casefold() if nameNode is not None else "")

        for node in styleRootNode.iter(f"{{{self.namespace}}}numFmt"):
            numberFormatObject[int(node.attrib.get("numFmtId", "-1"))] = node.attrib.get("formatCode", "")

            numberFormatDateObject.pop(int(node.attrib.get("numFmtId", "-1")), None)

        cellFormatNode = styleRootNode.find(f"{{{self.namespace}}}cellXfs")

        formatNodeList = [node for node in cellFormatNode if xmlNodeTag(node) == "xf"] if cellFormatNode is not None else []

        for a in range(len(formatNodeList)):
            fontId = int(formatNodeList[a].attrib.get("fontId", "0"))

            if fontId < len(fontNameList) and fontNameList[fontId] in symbolObject:
                resultObject["fontObject"][a] = fontNameList[fontId]

            numberFormatId = int(formatNodeList[a].attrib.get("numFmtId", "0"))

            if numberFormatId in numberFormatDateObject:
                resultObject["dateObject"][a] = numberFormatDateObject[numberFormatId]
            elif numberFormatId in numberFormatObject and self._dateFormatCheck(numberFormatObject[numberFormatId]):
                resultObject["dateObject"][a] = numberFormatObject[numberFormatId]
            elif numberFormatId in numberFormatObject:
                resultObject["formatObject"][a] = numberFormatObject[numberFormatId]

        return resultObject

    def _richValueList(self, zipFile):
        valueRootNode = xmlRootBuild("xl/richData/rdrichvalue.xml", zipFile)
        structureRootNode = xmlRootBuild("xl/richData/rdrichvaluestructure.xml", zipFile)

        if valueRootNode is None or structureRootNode is None:
            return []

        resultList = []

        structureNodeList = [structureNode for structureNode in structureRootNode if xmlNodeTag(structureNode) == "s"]

        keyList = [[keyNode.attrib.get("n", "") for keyNode in structureNode if xmlNodeTag(keyNode) == "k"] for structureNode in structureNodeList]

        for valueNode in valueRootNode:
            if xmlNodeTag(valueNode) != "rv":
                continue

            textList = [node.text if node.text is not None else "" for node in valueNode if xmlNodeTag(node) == "v"]

            structureIndex = int(valueNode.attrib.get("s", "-1"))

            nameList = keyList[structureIndex] if structureIndex >= 0 and structureIndex < len(keyList) else []

            valueObject = {nameList[a]: textList[a] for a in range(min(len(nameList), len(textList)))}

            isError = len(nameList) > 0 and structureNodeList[structureIndex].attrib.get("t", "") == self.typeRichError and self.keyRichError in valueObject and valueObject[self.keyRichError].isdigit() and int(valueObject[self.keyRichError]) in self.richErrorObject

            if self.keyRichText in valueObject:
                resultList.append(valueObject[self.keyRichText])
            elif isError:
                resultList.append(self.richErrorObject[int(valueObject[self.keyRichError])])
            else:
                resultList.append("")

        return resultList

    def _richTextBuild(self, zipFile):
        resultObject = {}

        metadataRootNode = xmlRootBuild("xl/metadata.xml", zipFile)

        if metadataRootNode is None:
            return resultObject

        valueList = self._richValueList(zipFile)

        typeNode = metadataRootNode.find(f"{{{self.namespace}}}metadataTypes")
        blockNode = metadataRootNode.find(f"{{{self.namespace}}}valueMetadata")

        typeList = [node.attrib.get("name", "") for node in typeNode] if typeNode is not None else []

        futureObject = {}

        for futureNode in metadataRootNode.iter(f"{{{self.namespace}}}futureMetadata"):
            futureObject[futureNode.attrib.get("name", "")] = [[int(node.attrib.get("i", "-1")) for node in recordNode.iter() if xmlNodeTag(node) == "rvb"] for recordNode in futureNode if xmlNodeTag(recordNode) == "bk"]

        recordNodeList = [node for node in blockNode if xmlNodeTag(node) == "bk"] if blockNode is not None else []

        for a in range(len(recordNodeList)):
            referenceNode = recordNodeList[a].find(f"{{{self.namespace}}}rc")

            typeIndex = int(referenceNode.attrib.get("t", "0")) - 1 if referenceNode is not None else -1
            recordIndex = int(referenceNode.attrib.get("v", "-1")) if referenceNode is not None else -1

            nameType = typeList[typeIndex] if typeIndex >= 0 and typeIndex < len(typeList) else ""

            indexList = futureObject[nameType][recordIndex] if nameType in futureObject and recordIndex >= 0 and recordIndex < len(futureObject[nameType]) else []

            if len(indexList) > 0 and indexList[0] >= 0 and indexList[0] < len(valueList) and valueList[indexList[0]] != "":
                resultObject[a + 1] = valueList[indexList[0]]

        return resultObject

    def _personBuild(self, zipFile):
        resultObject = {}

        pathObject = xmlRelationshipBuild("xl/workbook.xml", zipFile)

        for relationshipId in pathObject:
            rootNode = xmlRootBuild(pathObject[relationshipId]["path"], zipFile) if pathObject[relationshipId]["type"].endswith("/person") else None

            if rootNode is None:
                continue

            for node in rootNode:
                resultObject[node.attrib.get("id", "")] = node.attrib.get("displayName", "")

        return resultObject

    def _sheetBuild(self, zipFile):
        partList = xmlRelationshipNodeList("xl/workbook.xml", zipFile, f"{{{self.namespace}}}sheet")

        return [{"name": partObject["node"].attrib.get("name", ""), "path": partObject["path"]} for partObject in partList if "worksheets/" in partObject["path"]]

    def _dateSystemCheck(self, zipFile):
        propertyNode = xmlRootBuild("xl/workbook.xml", zipFile).find(f"{{{self.namespace}}}workbookPr")

        if propertyNode is None:
            return False

        return propertyNode.attrib.get("date1904", "0") not in valueFalseList

    def _columnIndex(self, reference):
        result = 0

        for character in reference:
            if character.isalpha():
                result = result * 26 + ord(character.upper()) - 64

        return result - 1

    def _rowIndex(self, reference):
        return int("".join(character for character in reference if character.isdigit())) - 1

    def _dateText(self, isDate1904, value):
        dateValue = (datetime.datetime(1904, 1, 1) if isDate1904 else datetime.datetime(1899, 12, 30)) + datetime.timedelta(days=value)

        if value < 1.0:
            return dateValue.strftime("%H:%M:%S")

        if value == int(value):
            return dateValue.strftime("%Y-%m-%d")

        return dateValue.strftime("%Y-%m-%d %H:%M:%S")

    def _dateLocale(self, tokenList):
        for a in range(len(tokenList)):
            match = re.fullmatch(self.patternFormatLocale, tokenList[a])

            if match is not None and match.group(1).replace("-", "_") in self.localeNameList:
                return match.group(1).replace("-", "_")

            if match is not None and re.fullmatch(self.patternFormatHexadecimal, match.group(1)) is not None and int(match.group(1), 16) % 65536 in self.localeObject:
                return self.localeObject[int(match.group(1), 16) % 65536]

        return ""

    def _datePartIndex(self, kindList, index, step):
        index += step

        while index >= 0 and index < len(kindList) and kindList[index] == "":
            index += step

        return index if index >= 0 and index < len(kindList) else -1

    def _dateFormat(self, formatCode, isDate1904, value):
        tokenList = [match.group(0) for match in re.finditer(self.patternFormatDate, re.findall(self.patternFormatSection, formatCode)[0])] if formatCode != "" else []

        kindList = []

        for a in range(len(tokenList)):
            token = tokenList[a].casefold()

            if re.fullmatch(self.patternFormatDateRun, token) is not None:
                kindList.append(token[0:1])
            elif re.fullmatch(self.patternFormatDateElapsed, token) is not None:
                kindList.append(token[1:2])
            else:
                kindList.append("")

        for a in range(len(kindList)):
            indexPrevious = self._datePartIndex(kindList, a, -1)
            indexNext = self._datePartIndex(kindList, a, 1)

            if kindList[a] == "m" and len(tokenList[a]) < 3 and tokenList[a][0:1] != "[" and ((indexPrevious != -1 and kindList[indexPrevious] == "h") or (indexNext != -1 and kindList[indexNext] == "s")):
                kindList[a] = "minute"

        locale = self._dateLocale(tokenList)

        isName = len([a for a in range(len(tokenList)) if kindList[a] in ["m", "d"] and len(tokenList[a]) > 2 and tokenList[a][0:1] != "["]) > 0
        isUnknown = len([a for a in range(len(tokenList)) if kindList[a] == "" and len(tokenList[a]) == 1 and unicodedata.category(tokenList[a])[0] == "L"]) > 0

        if len(tokenList) == 0 or isUnknown or (isName and locale == ""):
            return self._dateText(isDate1904, value)

        countFraction = max([0] + [len(token) - 1 for token in tokenList if re.fullmatch(self.patternFormatDateFraction, token) is not None])

        second = round(value * 86400, countFraction)

        dateValue = (datetime.datetime(1904, 1, 1) if isDate1904 else datetime.datetime(1899, 12, 30)) + datetime.timedelta(seconds=second)

        isHalf = len([token for token in tokenList if token.casefold() in self.formatHalfList]) > 0

        symbolObject = icu.DateFormatSymbols(icu.Locale(locale)) if isName else None

        result = ""

        for a in range(len(tokenList)):
            token = tokenList[a]

            count = len(token)

            if kindList[a] == "y":
                result += dateValue.strftime("%Y") if count > 2 else dateValue.strftime("%y")
            elif kindList[a] == "m" and token[0:1] == "[":
                result += str(int(second // 60)).zfill(count - 2)
            elif kindList[a] == "m" and count > 4:
                result += symbolObject.getMonths()[dateValue.month - 1][0:1]
            elif kindList[a] == "m" and count > 2:
                result += symbolObject.getMonths()[dateValue.month - 1] if count == 4 else symbolObject.getShortMonths()[dateValue.month - 1]
            elif kindList[a] == "m":
                result += str(dateValue.month).zfill(count)
            elif kindList[a] == "d" and count > 2:
                result += symbolObject.getWeekdays()[(dateValue.weekday() + 1) % 7 + 1] if count > 3 else symbolObject.getShortWeekdays()[(dateValue.weekday() + 1) % 7 + 1]
            elif kindList[a] == "d":
                result += str(dateValue.day).zfill(count)
            elif kindList[a] == "h" and token[0:1] == "[":
                result += str(int(second // 3600)).zfill(count - 2)
            elif kindList[a] == "h":
                result += str((dateValue.hour + 11) % 12 + 1 if isHalf else dateValue.hour).zfill(count)
            elif kindList[a] == "minute":
                result += str(dateValue.minute).zfill(count)
            elif kindList[a] == "s" and token[0:1] == "[":
                result += str(int(second)).zfill(count - 2)
            elif kindList[a] == "s":
                result += str(dateValue.second).zfill(count)
            elif token.casefold() in self.formatHalfList:
                result += token.split("/")[0 if dateValue.hour < 12 else 1]
            elif re.fullmatch(self.patternFormatDateFraction, token) is not None:
                result += "." + str(dateValue.microsecond).zfill(6)[0:count - 1]
            elif token[0:1] == "\"":
                result += token[1:-1]
            elif token[0:1] == "\\":
                result += token[1:]
            elif token[0:1] == "_":
                result += " "
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

        countDigit = len([token for token in tokenList if re.fullmatch(self.patternFormatDigit, token) is not None])
        countPercent = len([token for token in tokenList if token == "%"])

        if countDigit > 1 or len([token for token in tokenList if token in self.formatUnsupportedList]) > 0:
            return numberText(valueText)

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

    def _valueText(self, cellType, valueText, styleIndex, styleFormatObject, isDate1904):
        if cellType == "b":
            return "TRUE" if valueText == "1" else "FALSE"

        if cellType in self.typeTextList or re.fullmatch(patternNumber, valueText) is None:
            return valueText

        if styleIndex in styleFormatObject["dateObject"]:
            return self._dateFormat(styleFormatObject["dateObject"][styleIndex], isDate1904, float(valueText))

        if styleIndex in styleFormatObject["formatObject"]:
            return self._numberFormat(valueText, styleFormatObject["formatObject"][styleIndex])

        return numberText(valueText)

    def _cellText(self, cellNode, richTextObject, sharedStringList, styleFormatObject, isDate1904):
        cellType = cellNode.attrib.get("t", "n")

        valueNode = cellNode.find(f"{{{self.namespace}}}v")
        valueText = valueNode.text if valueNode is not None and valueNode.text is not None else ""

        styleText = cellNode.attrib.get("s", "")
        styleIndex = int(styleText) if styleText.isdigit() else -1

        valueIndex = cellNode.attrib.get("vm", "")

        if cellType == self.typeError and valueIndex != "":
            return richTextObject[int(valueIndex)] if int(valueIndex) in richTextObject else ""

        if cellType == "s" and valueText == "":
            return ""

        inlineNode = cellNode.find(f"{{{self.namespace}}}is") if cellType == "inlineStr" else None

        if cellType == "inlineStr" and inlineNode is None:
            return ""

        if cellType == "s" or cellType == "inlineStr":
            stringObject = sharedStringList[int(valueText)] if cellType == "s" else self._stringObject(inlineNode)

            return (symbolText(stringObject["text"], styleFormatObject["fontObject"][styleIndex]) if stringObject["isPlain"] and styleIndex in styleFormatObject["fontObject"] else stringObject["text"]).strip()

        text = self._valueText(cellType, valueText, styleIndex, styleFormatObject, isDate1904)

        return (symbolText(text, styleFormatObject["fontObject"][styleIndex]) if styleIndex in styleFormatObject["fontObject"] else text).strip()

    def _mergeObject(self, sheetRootNode):
        resultObject = {}

        for node in sheetRootNode.iter(f"{{{self.namespace}}}mergeCell"):
            referenceList = node.attrib.get("ref", "").split(":")

            if len(referenceList) == 2:
                resultObject[(self._rowIndex(referenceList[0]), self._columnIndex(referenceList[0]))] = {"rowEnd": self._rowIndex(referenceList[1]), "columnEnd": self._columnIndex(referenceList[1])}

        return resultObject

    def _cellList(self, sheetRootNode, richTextObject, sharedStringList, styleFormatObject, isDate1904):
        resultList = []

        mergeObject = self._mergeObject(sheetRootNode)

        row = -1

        for rowNode in sheetRootNode.iter(f"{{{self.namespace}}}row"):
            row = int(rowNode.attrib["r"]) - 1 if rowNode.attrib.get("r", "").isdigit() else row + 1

            column = -1

            for cellNode in rowNode:
                if xmlNodeTag(cellNode) != "c":
                    continue

                column = self._columnIndex(cellNode.attrib["r"]) if cellNode.attrib.get("r", "") != "" else column + 1

                text = self._cellText(cellNode, richTextObject, sharedStringList, styleFormatObject, isDate1904)

                if text == "":
                    continue

                endObject = mergeObject[(row, column)] if (row, column) in mergeObject else {"rowEnd": row, "columnEnd": column}

                resultList.append({"row": row, "column": column, "rowEnd": endObject["rowEnd"], "columnEnd": endObject["columnEnd"], "text": text})

        return resultList

    def _commentThreadBuild(self, rootNode, personObject):
        resultObject = {}

        for node in rootNode:
            textList = [childNode.text for childNode in node if xmlNodeTag(childNode) == "text" and childNode.text is not None]

            key = node.attrib.get("parentId", node.attrib.get("id", ""))

            resultObject.setdefault(key, []).append({
                "reference": node.attrib.get("ref", ""),
                "author": personObject[node.attrib.get("personId", "")] if node.attrib.get("personId", "") in personObject else "",
                "text": " ".join(textList)
            })

        return resultObject

    def _commentList(self, pathSheet, zipFile, personObject):
        resultList = []

        commentList = []

        threadObject = {}

        pathObject = xmlRelationshipBuild(pathSheet, zipFile)

        for relationshipId in pathObject:
            typeLast = pathObject[relationshipId]["type"].split("/")[-1]

            rootNode = xmlRootBuild(pathObject[relationshipId]["path"], zipFile) if typeLast in self.commentTypeList else None

            if rootNode is None:
                continue

            if typeLast == self.commentTypeThread:
                threadObject.update(self._commentThreadBuild(rootNode, personObject))

                continue

            authorList = [node.text if node.text is not None else "" for node in rootNode.iter(f"{{{self.namespace}}}author")]

            for node in rootNode.iter(f"{{{self.namespace}}}comment"):
                textNode = node.find(f"{{{self.namespace}}}text")

                authorIndex = int(node.attrib.get("authorId", "-1"))

                commentList.append({
                    "reference": node.attrib.get("ref", ""),
                    "author": authorList[authorIndex] if authorIndex >= 0 and authorIndex < len(authorList) else "",
                    "text": self._stringObject(textNode)["text"] if textNode is not None else ""
                })

        for a in range(len(commentList)):
            key = commentList[a]["author"][len(self.prefixThread):] if commentList[a]["author"].startswith(self.prefixThread) else ""

            resultList += threadObject.pop(key) if key in threadObject else [commentList[a]]

        for key in threadObject:
            resultList += threadObject[key]

        return [commentObject for commentObject in resultList if commentObject["reference"] != "" and commentObject["text"].strip() != ""]

    def _commentWrite(self, commentList, count, cellList):
        resultList = []

        for a in range(len(commentList)):
            name = f"{markComment}{count + a + 1}"

            row = self._rowIndex(commentList[a]["reference"])
            column = self._columnIndex(commentList[a]["reference"])

            cellMatchList = [cellObject for cellObject in cellList if cellObject["row"] == row and cellObject["column"] == column]

            if len(cellMatchList) == 0:
                cellMatchList.append({"row": row, "column": column, "rowEnd": row, "columnEnd": column, "text": ""})

                cellList.append(cellMatchList[0])

            cellMatchList[0]["text"] += noteMark(name)

            resultList.append({"kind": "text", "label": labelText, "text": noteText(name, commentList[a]["author"], " ".join(commentList[a]["text"].split()))})

        return resultList

    def _groupList(self, elementList, nameStart, nameEnd):
        resultList = []

        elementSortedList = sorted(elementList, key=lambda elementObject: elementObject[nameStart])

        end = 0

        for a in range(len(elementSortedList)):
            if a == 0 or elementSortedList[a][nameStart] > end + 1:
                resultList.append([])

                end = elementSortedList[a][nameEnd]

            resultList[len(resultList) - 1].append(elementSortedList[a])

            end = max(end, elementSortedList[a][nameEnd])

        return resultList

    def _blockList(self, elementList):
        groupList = self._groupList(elementList, "row", "rowEnd")

        if len(groupList) == 1:
            groupList = self._groupList(elementList, "column", "columnEnd")

        if len(groupList) == 1:
            return [elementList]

        return [blockObject for a in range(len(groupList)) for blockObject in self._blockList(groupList[a])]

    def _blockWrite(self, cellList):
        if len(cellList) == 1:
            return {"kind": "text", "label": labelText, "text": cellList[0]["text"]}

        row = min(cellObject["row"] for cellObject in cellList)
        column = min(cellObject["column"] for cellObject in cellList)

        gridList = [{"row": cellObject["row"] - row, "column": cellObject["column"] - column, "rowSpan": cellObject["rowEnd"] - cellObject["row"] + 1, "columnSpan": cellObject["columnEnd"] - cellObject["column"] + 1, "text": cellObject["text"]} for cellObject in cellList]

        return {"kind": "table", "label": labelTable, "rowList": gridRowList(gridList, max(cellObject["rowEnd"] for cellObject in cellList) - row + 1, max(cellObject["columnEnd"] for cellObject in cellList) - column + 1)}

    def _anchorIndex(self, anchorNode, tagPoint, tagValue):
        for pointNode in anchorNode:
            if xmlNodeTag(pointNode) != tagPoint:
                continue

            for valueNode in pointNode:
                if xmlNodeTag(valueNode) == tagValue and valueNode.text is not None:
                    return int(valueNode.text)

        return None

    def _shapeItemList(self, anchorNode):
        resultList = []

        for bodyNode in anchorNode.iter():
            if xmlNodeTag(bodyNode) != "txBody":
                continue

            for paragraphNode in bodyNode.iter(f"{{{namespaceDrawing}}}p"):
                text = xmlParagraphText(paragraphNode, characterDrawingObject, "")

                if text != "":
                    resultList.append({"kind": "text", "label": labelText, "text": text})

        return resultList

    def _drawingList(self, pathSheet, zipFile):
        resultList = []

        pathSheetObject = xmlRelationshipBuild(pathSheet, zipFile)

        for relationshipSheetId in pathSheetObject:
            if pathSheetObject[relationshipSheetId]["type"].endswith("/drawing") == False:
                continue

            pathDrawing = pathSheetObject[relationshipSheetId]["path"]

            pathObject = xmlRelationshipBuild(pathDrawing, zipFile)

            rootNode = xmlRootBuild(pathDrawing, zipFile)

            xmlFallbackRemove(rootNode)

            drawingSymbolWrite(rootNode)

            self.latex.execute(rootNode)

            for anchorNode in rootNode.iter():
                row = self._anchorIndex(anchorNode, "from", "row")
                column = self._anchorIndex(anchorNode, "from", "col")

                if row is None or column is None:
                    continue

                chartNode = anchorNode.find(f".//{{{namespaceChart}}}chart")

                relationshipId = chartNode.attrib.get(f"{{{namespaceRelationship}}}id", "") if chartNode is not None else ""

                itemList = xmlChartItemList(xmlRootBuild(pathObject[relationshipId]["path"], zipFile)) if relationshipId in pathObject else []

                itemList += self._shapeItemList(anchorNode)

                if len(itemList) > 0:
                    resultList.append({"row": row, "column": column, "itemList": itemList})

        return sorted(resultList, key=lambda drawingObject: (drawingObject["row"], drawingObject["column"]))

    def execute(self, fileInput):
        resultList = []

        zipFile = zipfile.ZipFile(fileInput)

        sharedStringRootNode = xmlRootBuild("xl/sharedStrings.xml", zipFile)
        styleRootNode = xmlRootBuild("xl/styles.xml", zipFile)

        sharedStringList = self._sharedStringBuild(sharedStringRootNode) if sharedStringRootNode is not None else []
        styleFormatObject = self._styleFormatBuild(styleRootNode) if styleRootNode is not None else {"dateObject": {}, "formatObject": {}, "fontObject": {}}

        richTextObject = self._richTextBuild(zipFile)

        personObject = self._personBuild(zipFile)

        sheetList = self._sheetBuild(zipFile)

        isDate1904 = self._dateSystemCheck(zipFile)

        countComment = 0

        for a in range(len(sheetList)):
            cellList = self._cellList(xmlRootBuild(sheetList[a]["path"], zipFile), richTextObject, sharedStringList, styleFormatObject, isDate1904)

            commentList = self._commentWrite(self._commentList(sheetList[a]["path"], zipFile, personObject), countComment, cellList)

            countComment += len(commentList)

            resultList.append({"kind": "title", "label": labelTitle, "level": 1, "text": sheetList[a]["name"]})

            blockList = self._blockList(cellList) if len(cellList) > 0 else []

            for b in range(len(blockList)):
                resultList.append(self._blockWrite(blockList[b]))

            drawingList = self._drawingList(sheetList[a]["path"], zipFile)

            for b in range(len(drawingList)):
                resultList += drawingList[b]["itemList"]

            resultList += commentList

        zipFile.close()

        return resultList

    def __init__(self, latex):
        self.latex = latex

        self.namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

        self.tagSkip = "rPh"

        self.typeError = "e"
        self.typeTextList = ["str", self.typeError]

        self.keyRichText = "_DisplayString"
        self.keyRichError = "errorType"
        self.typeRichError = "_error"
        self.richErrorObject = {4: "#NAME?", 8: "#SPILL!", 9: "#CONNECT!", 10: "#BLOCKED!", 11: "#UNKNOWN!", 12: "#FIELD!", 13: "#CALC!", 14: "#BUSY!", 17: "#BUSY!", 19: "#TIMEOUT!"}

        self.commentTypeThread = "threadedComment"
        self.commentTypeList = [self.commentTypeThread, "comments"]
        self.prefixThread = "tc="

        self.numberFormatDateObject = {14: "", 15: "d-mmm-yy", 16: "d-mmm", 17: "mmm-yy", 18: "h:mm AM/PM", 19: "h:mm:ss AM/PM", 20: "h:mm", 21: "h:mm:ss", 22: "", 45: "mm:ss", 46: "[h]:mm:ss", 47: "mmss.0"}

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

        self.patternFormatDate = r"\"[^\"]*\"|\\.|_.|\*.|\[[^\]]*\]|[Aa][Mm]/[Pp][Mm]|[Aa]/[Pp]|([ymdhsYMDHS])\1*|\.0+|."
        self.patternFormatDateRun = r"([ymdhs])\1*"
        self.patternFormatDateElapsed = r"\[(h+|m+|s+)\]"
        self.patternFormatDateFraction = r"\.0+"
        self.patternFormatSecondFraction = r"(?<=[sS])\.0+"
        self.patternFormatLocale = r"\[\$[^-\]]*-([^\]]+)\]"
        self.patternFormatHexadecimal = r"[0-9A-Fa-f]+"
        self.formatHalfList = ["am/pm", "a/p"]

        self.localeNameList = list(icu.Locale.getAvailableLocales())
        self.localeObject = {icu.Locale(name).getLCID(): name for name in self.localeNameList if icu.Locale(name).getLCID() != 0}

        self.textFormatGeneral = "general"
