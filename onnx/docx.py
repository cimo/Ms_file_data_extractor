import sys
import re
import zipfile
import unicodedata

sys.dont_write_bytecode = True

# Source
from helper import numberMarker, numberMarkerList, symbolText, symbolObject, noteMark, noteText, markComment, xmlRootBuild, xmlNodeTag, xmlNodeValue, xmlAttributeValue, xmlFallbackRemove, xmlControlValue, xmlParagraphText, xmlRelationshipBuild, xmlChartItemList, gridRowList, labelText, labelTable, labelTitle, namespaceChart, namespaceRelationship, tagControlList

class Docx:
    def _styleBuild(self, styleRootNode):
        resultObject = {}

        for styleNode in styleRootNode.iter(f"{{{self.namespace}}}style"):
            outlineNode = styleNode.find(f"{{{self.namespace}}}pPr/{{{self.namespace}}}outlineLvl")
            nameNode = styleNode.find(f"{{{self.namespace}}}name")
            basedNode = styleNode.find(f"{{{self.namespace}}}basedOn")
            numberNode = styleNode.find(f"{{{self.namespace}}}pPr/{{{self.namespace}}}numPr/{{{self.namespace}}}numId")
            levelNode = styleNode.find(f"{{{self.namespace}}}pPr/{{{self.namespace}}}numPr/{{{self.namespace}}}ilvl")

            resultObject[styleNode.attrib.get(f"{{{self.namespace}}}styleId", "")] = {
                "outline": xmlNodeValue(outlineNode, self.namespace) if outlineNode is not None else "",
                "name": xmlNodeValue(nameNode, self.namespace).casefold() if nameNode is not None else "",
                "based": xmlNodeValue(basedNode, self.namespace) if basedNode is not None else "",
                "number": xmlNodeValue(numberNode, self.namespace) if numberNode is not None else "",
                "level": xmlNodeValue(levelNode, self.namespace) if levelNode is not None else ""
            }

        return resultObject

    def _languageBuild(self, styleRootNode):
        languageNode = styleRootNode.find(f"{{{self.namespace}}}docDefaults/{{{self.namespace}}}rPrDefault/{{{self.namespace}}}rPr/{{{self.namespace}}}lang")

        return xmlNodeValue(languageNode, self.namespace) if languageNode is not None else ""

    def _levelBuild(self, levelNode):
        resultObject = {"start": 1, "format": "decimal", "text": "", "isLegal": False, "fontSymbol": "", "style": ""}

        for node in levelNode:
            tag = xmlNodeTag(node)

            if tag == "start":
                resultObject["start"] = int(xmlNodeValue(node, self.namespace))
            elif tag == "numFmt":
                resultObject["format"] = xmlNodeValue(node, self.namespace)
            elif tag == "lvlText":
                resultObject["text"] = xmlNodeValue(node, self.namespace)
            elif tag == "isLgl":
                resultObject["isLegal"] = True
            elif tag == "pStyle":
                resultObject["style"] = xmlNodeValue(node, self.namespace)
            elif tag == "rPr":
                fontNode = node.find(f"{{{self.namespace}}}rFonts")

                resultObject["fontSymbol"] = xmlAttributeValue(fontNode, ["ascii", "hAnsi"]).casefold() if fontNode is not None else ""

        return resultObject

    def _numberingBuild(self, numberingRootNode):
        resultObject = {"abstract": {}, "instance": {}}

        for abstractNode in numberingRootNode.iter(f"{{{self.namespace}}}abstractNum"):
            levelObject = {}

            for levelNode in abstractNode.iter(f"{{{self.namespace}}}lvl"):
                levelObject[int(levelNode.attrib.get(f"{{{self.namespace}}}ilvl", "0"))] = self._levelBuild(levelNode)

            resultObject["abstract"][abstractNode.attrib.get(f"{{{self.namespace}}}abstractNumId", "")] = levelObject

        for instanceNode in numberingRootNode.iter(f"{{{self.namespace}}}num"):
            abstractNode = instanceNode.find(f"{{{self.namespace}}}abstractNumId")

            startObject = {}

            for overrideNode in instanceNode.iter(f"{{{self.namespace}}}lvlOverride"):
                startNode = overrideNode.find(f"{{{self.namespace}}}startOverride")

                if startNode is not None:
                    startObject[int(overrideNode.attrib.get(f"{{{self.namespace}}}ilvl", "0"))] = int(xmlNodeValue(startNode, self.namespace))

            resultObject["instance"][instanceNode.attrib.get(f"{{{self.namespace}}}numId", "")] = {"abstract": xmlNodeValue(abstractNode, self.namespace) if abstractNode is not None else "", "start": startObject}

        return resultObject

    def _placeholderItemRemove(self, documentObject, rootNode):
        glossaryRootNode = xmlRootBuild("word/glossary/document.xml", documentObject["zip"])

        if glossaryRootNode is None:
            return

        textObject = {}

        for partNode in glossaryRootNode.iter(f"{{{self.namespace}}}docPart"):
            nameNode = partNode.find(f"{{{self.namespace}}}docPartPr/{{{self.namespace}}}name")
            bodyNode = partNode.find(f"{{{self.namespace}}}docPartBody")

            if nameNode is not None and bodyNode is not None:
                textObject[xmlNodeValue(nameNode, self.namespace)] = " ".join(xmlParagraphText(paragraphNode, self.characterObject, self.tagSkip) for paragraphNode in bodyNode.iter(f"{{{self.namespace}}}p"))

        for propertyNode in rootNode.iter(f"{{{self.namespace}}}sdtPr"):
            partNode = propertyNode.find(f"{{{self.namespace}}}placeholder/{{{self.namespace}}}docPart")

            if partNode is None or xmlNodeValue(partNode, self.namespace) not in textObject:
                continue

            textPlaceholder = textObject[xmlNodeValue(partNode, self.namespace)]

            for listNode in propertyNode:
                if xmlNodeTag(listNode) not in tagControlList:
                    continue

                for itemNode in list(listNode):
                    if xmlAttributeValue(itemNode, ["displayText", "value"]) == textPlaceholder:
                        listNode.remove(itemNode)

    def _controlUnwrap(self, parentNode):
        index = 0

        while index < len(parentNode):
            node = parentNode[index]

            self._controlUnwrap(node)

            contentNode = node.find(f"{{{self.namespace}}}sdtContent") if xmlNodeTag(node) == "sdt" else None

            if contentNode is None or len([childNode for childNode in contentNode if xmlNodeTag(childNode) in self.tagBlockList]) == 0:
                index += 1

                continue

            value = xmlControlValue(node)

            if value != None:
                textNodeList = list(contentNode.iter(f"{{{self.namespace}}}t"))

                for a in range(len(textNodeList)):
                    textNodeList[a].text = value if a == 0 else ""

            childList = list(contentNode)

            parentNode.remove(node)

            for a in range(len(childList)):
                parentNode.insert(index + a, childList[a])

            index += len(childList)

    def _noteMarkWrite(self, rootNode):
        for node in rootNode.iter():
            tag = xmlNodeTag(node)

            if tag in self.noteMarkObject:
                node.text = noteMark(f"{self.noteMarkObject[tag]}{node.attrib.get(f'{{{self.namespace}}}id', '')}")
                node.tag = f"{{{self.namespace}}}t"

    def _symbolWrite(self, rootNode):
        for runNode in rootNode.iter(f"{{{self.namespace}}}r"):
            fontNode = runNode.find(f"{{{self.namespace}}}rPr/{{{self.namespace}}}rFonts")

            font = xmlAttributeValue(fontNode, ["ascii", "hAnsi"]).casefold() if fontNode is not None else ""

            for node in runNode:
                tag = xmlNodeTag(node)

                if tag == "t" and font in symbolObject and node.text is not None:
                    node.text = symbolText(node.text, font)
                elif tag == "sym" and node.attrib.get(f"{{{self.namespace}}}font", "").casefold() in symbolObject:
                    node.text = symbolText(chr(int(node.attrib.get(f"{{{self.namespace}}}char", "0"), 16)), node.attrib.get(f"{{{self.namespace}}}font", "").casefold())
                    node.tag = f"{{{self.namespace}}}t"

    def _styleFind(self, paragraphNode):
        styleNode = paragraphNode.find(f"{{{self.namespace}}}pPr/{{{self.namespace}}}pStyle")

        return xmlNodeValue(styleNode, self.namespace) if styleNode is not None else ""

    def _numberFind(self, paragraphNode, documentObject):
        numberNode = paragraphNode.find(f"{{{self.namespace}}}pPr/{{{self.namespace}}}numPr/{{{self.namespace}}}numId")
        levelNode = paragraphNode.find(f"{{{self.namespace}}}pPr/{{{self.namespace}}}numPr/{{{self.namespace}}}ilvl")

        resultObject = {"number": xmlNodeValue(numberNode, self.namespace) if numberNode is not None else "", "level": xmlNodeValue(levelNode, self.namespace) if levelNode is not None else "", "style": ""}

        style = self._styleFind(paragraphNode)

        styleVisitedList = []

        while resultObject["number"] == "" and style in documentObject["style"] and style not in styleVisitedList:
            resultObject["number"] = documentObject["style"][style]["number"]
            resultObject["level"] = documentObject["style"][style]["level"]
            resultObject["style"] = style

            styleVisitedList.append(style)

            style = documentObject["style"][style]["based"]

        return resultObject

    def _languageFind(self, paragraphNode, documentObject):
        languageNodeList = [node for node in [paragraphNode.find(f"{{{self.namespace}}}pPr/{{{self.namespace}}}rPr/{{{self.namespace}}}lang"), paragraphNode.find(f"{{{self.namespace}}}r/{{{self.namespace}}}rPr/{{{self.namespace}}}lang")] if node is not None and xmlNodeValue(node, self.namespace) != ""]

        return xmlNodeValue(languageNodeList[0], self.namespace) if len(languageNodeList) > 0 else documentObject["language"]

    def _markerText(self, paragraphNode, documentObject):
        numberObject = self._numberFind(paragraphNode, documentObject)

        instanceObject = documentObject["numbering"]["instance"]

        if numberObject["number"] not in instanceObject or instanceObject[numberObject["number"]]["abstract"] not in documentObject["numbering"]["abstract"]:
            return ""

        abstract = instanceObject[numberObject["number"]]["abstract"]

        levelObject = documentObject["numbering"]["abstract"][abstract]

        styleLevelList = [level for level in levelObject if levelObject[level]["style"] == numberObject["style"] and numberObject["style"] != ""]

        level = int(numberObject["level"]) if numberObject["level"] != "" else (styleLevelList[0] if len(styleLevelList) > 0 else 0)

        if level not in levelObject:
            return ""

        if abstract not in documentObject["counter"]:
            documentObject["counter"][abstract] = {}

        counterObject = documentObject["counter"][abstract]

        if numberObject["number"] not in documentObject["instance"]:
            documentObject["instance"].append(numberObject["number"])

            for levelStart in instanceObject[numberObject["number"]]["start"]:
                counterObject[levelStart] = instanceObject[numberObject["number"]]["start"][levelStart] - 1

        for levelOther in sorted(levelObject):
            if levelOther < level and levelOther not in counterObject:
                counterObject[levelOther] = levelObject[levelOther]["start"]
            elif levelOther > level and levelOther in counterObject:
                counterObject.pop(levelOther)

        counterObject[level] = counterObject[level] + 1 if level in counterObject else levelObject[level]["start"]

        if levelObject[level]["format"] == "bullet":
            text = symbolText(levelObject[level]["text"], levelObject[level]["fontSymbol"]) if levelObject[level]["fontSymbol"] in symbolObject else levelObject[level]["text"]

            return "".join(character for character in text if unicodedata.category(character) != "Co").strip()

        result = levelObject[level]["text"]

        language = self._languageFind(paragraphNode, documentObject)

        for levelOther in sorted(levelObject):
            format = "decimal" if levelObject[level]["isLegal"] else levelObject[levelOther]["format"]

            marker = numberMarker(counterObject[levelOther], format, language) if f"%{levelOther + 1}" in result and levelOther in counterObject and format in numberMarkerList else ""

            if marker != "":
                result = result.replace(f"%{levelOther + 1}", marker)

        return "" if "%" in result else result.strip()

    def _paragraphText(self, paragraphNode, documentObject):
        text = xmlParagraphText(paragraphNode, self.characterObject, self.tagSkip)

        if text == "":
            return text

        return f"{self._markerText(paragraphNode, documentObject)} {text}".strip()

    def _outlineLevel(self, outline):
        if outline.isdigit() and int(outline) < self.countOutline:
            return int(outline) + 1

        return 0

    def _titleLevel(self, paragraphNode, styleObject):
        outlineNode = paragraphNode.find(f"{{{self.namespace}}}pPr/{{{self.namespace}}}outlineLvl")

        if outlineNode is not None:
            return self._outlineLevel(xmlNodeValue(outlineNode, self.namespace))

        style = self._styleFind(paragraphNode)

        styleVisitedList = []

        while style in styleObject and style not in styleVisitedList:
            if styleObject[style]["outline"] != "":
                return self._outlineLevel(styleObject[style]["outline"])

            if styleObject[style]["name"] in self.styleTitleList:
                return 1

            match = re.fullmatch(self.patternStyleHeading, styleObject[style]["name"])

            if match is not None:
                return int(match.group(1))

            styleVisitedList.append(style)

            style = styleObject[style]["based"]

        return 0

    def _chartBuild(self, paragraphNode, documentObject):
        resultList = []

        for chartNode in paragraphNode.iter(f"{{{namespaceChart}}}chart"):
            relationshipId = chartNode.attrib.get(f"{{{namespaceRelationship}}}id", "")

            chartRootNode = xmlRootBuild(documentObject["path"][relationshipId]["path"], documentObject["zip"]) if relationshipId in documentObject["path"] else None

            if chartRootNode is not None:
                resultList += xmlChartItemList(chartRootNode)

        return resultList

    def _nodeList(self, containerNode, tag):
        resultList = []

        for node in containerNode:
            if xmlNodeTag(node) == tag:
                resultList.append(node)
            elif xmlNodeTag(node) in self.tagWrapList:
                resultList += self._nodeList(node, tag)

        return resultList

    def _cellPropertyValue(self, cellNode, tagProperty):
        propertyNode = cellNode.find(f"{{{self.namespace}}}tcPr/{{{self.namespace}}}{tagProperty}")

        if propertyNode is None:
            return None

        return xmlNodeValue(propertyNode, self.namespace)

    def _nodeText(self, containerNode, documentObject):
        textList = []

        for paragraphNode in containerNode.iter(f"{{{self.namespace}}}p"):
            textList.append(self._paragraphText(paragraphNode, documentObject))

        return " ".join(text for text in textList if text != "")

    def _tableBuild(self, tableNode, documentObject):
        cellList = []

        openObject = {}

        rowNodeList = self._nodeList(tableNode, "tr")

        cellNodeList = [self._nodeList(rowNode, "tc") for rowNode in rowNodeList]

        if len([cellNode for a in range(len(cellNodeList)) for cellNode in cellNodeList[a]]) == 1:
            return self._blockBuild(cellNodeList[0][0], documentObject)

        countColumn = 0

        for a in range(len(rowNodeList)):
            column = 0

            for cellNode in cellNodeList[a]:
                span = self._cellPropertyValue(cellNode, "gridSpan")
                merge = self._cellPropertyValue(cellNode, "vMerge")

                columnSpan = int(span) if span is not None and span.isdigit() else 1

                if merge is not None and merge != self.valueMergeStart and column in openObject:
                    openObject[column]["rowSpan"] += 1
                else:
                    openObject[column] = {"row": a, "column": column, "rowSpan": 1, "columnSpan": columnSpan, "text": self._nodeText(cellNode, documentObject)}

                    cellList.append(openObject[column])

                column += columnSpan

            countColumn = max(countColumn, column)

        if len([cellObject for cellObject in cellList if cellObject["text"] != ""]) == 0:
            return []

        return [{"kind": "table", "label": labelTable, "rowList": gridRowList(cellList, len(rowNodeList), countColumn)}]

    def _paragraphBuild(self, paragraphNode, documentObject):
        resultList = []

        text = self._paragraphText(paragraphNode, documentObject)

        level = self._titleLevel(paragraphNode, documentObject["style"])

        if text != "" and level > 0:
            resultList.append({"kind": "title", "label": labelTitle, "level": level, "text": text})
        elif text != "":
            resultList.append({"kind": "text", "label": labelText, "text": text})

        resultList += self._chartBuild(paragraphNode, documentObject)

        for node in paragraphNode.iter(f"{{{self.namespace}}}{self.tagSkip}"):
            resultList += self._blockBuild(node, documentObject)

        return resultList

    def _blockBuild(self, containerNode, documentObject):
        resultList = []

        for node in containerNode:
            tag = xmlNodeTag(node)

            if tag == "p":
                resultList += self._paragraphBuild(node, documentObject)
            elif tag == "tbl":
                resultList += self._tableBuild(node, documentObject)
            elif tag not in self.tagPropertyList:
                resultList += self._blockBuild(node, documentObject)

        return resultList

    def _noteBuild(self, documentObject):
        resultList = []

        for relationshipId in documentObject["path"]:
            typeLast = documentObject["path"][relationshipId]["type"].split("/")[-1]

            rootNode = xmlRootBuild(documentObject["path"][relationshipId]["path"], documentObject["zip"]) if typeLast in self.noteTypeObject else None

            if rootNode is None:
                continue

            xmlFallbackRemove(rootNode)

            self.latex.execute(rootNode)

            self._symbolWrite(rootNode)

            for noteNode in rootNode:
                text = self._nodeText(noteNode, documentObject)

                if text != "" and noteNode.attrib.get(f"{{{self.namespace}}}type", "") not in self.noteTypeSkipList:
                    resultList.append({"kind": "text", "label": labelText, "text": noteText(f"{self.noteTypeObject[typeLast]}{noteNode.attrib.get(f'{{{self.namespace}}}id', '')}", noteNode.attrib.get(f"{{{self.namespace}}}author", ""), text)})

        return resultList

    def execute(self, fileInput):
        resultList = []

        zipFile = zipfile.ZipFile(fileInput)

        rootNode = xmlRootBuild("word/document.xml", zipFile)

        styleRootNode = xmlRootBuild("word/styles.xml", zipFile)
        numberingRootNode = xmlRootBuild("word/numbering.xml", zipFile)

        documentObject = {
            "zip": zipFile,
            "path": xmlRelationshipBuild("word/document.xml", zipFile),
            "style": self._styleBuild(styleRootNode) if styleRootNode is not None else {},
            "numbering": self._numberingBuild(numberingRootNode) if numberingRootNode is not None else {"abstract": {}, "instance": {}},
            "counter": {},
            "instance": [],
            "language": self._languageBuild(styleRootNode) if styleRootNode is not None else ""
        }

        xmlFallbackRemove(rootNode)

        self.latex.execute(rootNode)

        self._placeholderItemRemove(documentObject, rootNode)
        self._controlUnwrap(rootNode)
        self._noteMarkWrite(rootNode)
        self._symbolWrite(rootNode)

        resultList += self._blockBuild(rootNode.find(f"{{{self.namespace}}}body"), documentObject)

        resultList += self._noteBuild(documentObject)

        zipFile.close()

        return resultList

    def __init__(self, latex):
        self.latex = latex

        self.namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

        self.characterObject = {"tab": " ", "br": " ", "cr": " ", "noBreakHyphen": "-"}
        self.tagSkip = "txbxContent"
        self.tagBlockList = ["p", "tbl", "tr", "tc"]
        self.tagWrapList = ["sdt", "sdtContent", "customXml", "smartTag", "ins"]
        self.tagPropertyList = ["sectPr", "tblPr", "tblGrid", "trPr", "tcPr", "pPr"]

        self.valueMergeStart = "restart"

        self.noteMarkObject = {"footnoteReference": "", "endnoteReference": "e", "commentReference": markComment}
        self.noteTypeObject = {"footnotes": "", "endnotes": "e", "comments": markComment}
        self.noteTypeSkipList = ["separator", "continuationSeparator", "continuationNotice"]

        self.styleTitleList = ["title"]

        self.patternStyleHeading = r"heading (\d)"

        self.countOutline = 9
