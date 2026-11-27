import sys
import re
import zipfile
import unicodedata

sys.dont_write_bytecode = True

# Source
from helper import numberMarker, textBullet, noteText, markComment, symbolText, symbolObject, drawingSymbolWrite, drawingRunSymbolWrite, xmlRootBuild, xmlFallbackRemove, xmlNodeTag, xmlParagraphText, xmlRelationshipBuild, xmlRelationshipNodeList, xmlChartItemList, gridRowList, labelText, labelTable, labelTitle, namespaceDrawing, namespaceChart, namespaceRelationship, characterDrawingObject

class Pptx:
    def _authorBuild(self, zipFile):
        resultObject = {}

        pathObject = xmlRelationshipBuild("ppt/presentation.xml", zipFile)

        for relationshipId in pathObject:
            rootNode = xmlRootBuild(pathObject[relationshipId]["path"], zipFile) if pathObject[relationshipId]["type"].split("/")[-1] in self.authorTypeList else None

            if rootNode is None:
                continue

            for node in rootNode:
                resultObject[node.attrib.get("id", "")] = node.attrib.get("name", "")

        return resultObject

    def _slideBuild(self, zipFile):
        return [partObject["path"] for partObject in xmlRelationshipNodeList("ppt/presentation.xml", zipFile, f"{{{self.namespace}}}sldId")]

    def _boxBuild(self, transformNode, transformObject):
        if transformNode is None:
            return None

        offsetNode = transformNode.find(f"{{{namespaceDrawing}}}off")
        extentNode = transformNode.find(f"{{{namespaceDrawing}}}ext")

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

    def _placeholderCollect(self, rootNode, resultObject):
        if rootNode is None:
            return

        for shapeNode in rootNode.iter(f"{{{self.namespace}}}sp"):
            placeholderNode = shapeNode.find(f"{{{self.namespace}}}nvSpPr/{{{self.namespace}}}nvPr/{{{self.namespace}}}ph")

            if placeholderNode is None:
                continue

            entryObject = {"bbox": self._boxBuild(shapeNode.find(f"{{{self.namespace}}}spPr/{{{namespaceDrawing}}}xfrm"), None), "styleNode": shapeNode.find(f"{{{self.namespace}}}txBody/{{{namespaceDrawing}}}lstStyle")}

            if "idx" in placeholderNode.attrib:
                resultObject[f"idx{placeholderNode.attrib['idx']}"] = entryObject

            resultObject[f"type{placeholderNode.attrib.get('type', 'body')}"] = entryObject

    def _placeholderBuild(self, styleDefaultNode, pathObject, zipFile):
        resultObject = {"layout": {}, "master": {}, "style": {}, "default": styleDefaultNode}

        for relationshipId in pathObject:
            if pathObject[relationshipId]["type"].endswith("/slideLayout") == False:
                continue

            pathLayout = pathObject[relationshipId]["path"]

            self._placeholderCollect(xmlRootBuild(pathLayout, zipFile), resultObject["layout"])

            pathLayoutObject = xmlRelationshipBuild(pathLayout, zipFile)

            for relationshipLayoutId in pathLayoutObject:
                if pathLayoutObject[relationshipLayoutId]["type"].endswith("/slideMaster") == False:
                    continue

                masterRootNode = xmlRootBuild(pathLayoutObject[relationshipLayoutId]["path"], zipFile)

                self._placeholderCollect(masterRootNode, resultObject["master"])

                styleNode = masterRootNode.find(f"{{{self.namespace}}}txStyles") if masterRootNode is not None else None

                resultObject["style"] = {xmlNodeTag(node): node for node in styleNode} if styleNode is not None else {}

        return resultObject

    def _groupTransform(self, groupNode, transformObject):
        transformNode = groupNode.find(f"{{{self.namespace}}}grpSpPr/{{{namespaceDrawing}}}xfrm")

        if transformNode is None:
            return transformObject

        bboxList = self._boxBuild(transformNode, transformObject)

        childOffsetNode = transformNode.find(f"{{{namespaceDrawing}}}chOff")
        childExtentNode = transformNode.find(f"{{{namespaceDrawing}}}chExt")

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

    def _placeholderEntryList(self, placeholderNode, placeholderObject):
        resultList = []

        placeholderType = placeholderNode.attrib.get("type", "body")

        keyList = [f"idx{placeholderNode.attrib.get('idx', '')}", f"type{placeholderType}"]

        entryLayoutList = [placeholderObject["layout"][key] for key in keyList if key in placeholderObject["layout"]]

        if len(entryLayoutList) > 0:
            resultList.append(entryLayoutList[0])

        keyMaster = f"type{self._placeholderMaster(placeholderType)}"

        if keyMaster in placeholderObject["master"]:
            resultList.append(placeholderObject["master"][keyMaster])

        return resultList

    def _placeholderMaster(self, placeholderType):
        return self.placeholderMasterObject[placeholderType] if placeholderType in self.placeholderMasterObject else placeholderType

    def _placeholderBox(self, placeholderNode, placeholderObject):
        bboxList = [entryObject["bbox"] for entryObject in self._placeholderEntryList(placeholderNode, placeholderObject) if entryObject["bbox"] is not None]

        return bboxList[0] if len(bboxList) > 0 else None

    def _regionBuild(self, label, bboxList, itemList):
        return {"label": label, "score": 0.0, "bbox": bboxList, "itemList": itemList, "lineList": [], "rowList": [], "isRightFirst": False}

    def _levelNodeList(self, paragraphNode, textBodyNode, placeholderNode, placeholderObject):
        propertyNode = paragraphNode.find(f"{{{namespaceDrawing}}}pPr")

        level = int(propertyNode.attrib.get("lvl", "0")) if propertyNode is not None else 0

        styleNodeList = [textBodyNode.find(f"{{{namespaceDrawing}}}lstStyle")]

        nameStyle = self.styleOther

        if placeholderNode is not None:
            styleNodeList += [entryObject["styleNode"] for entryObject in self._placeholderEntryList(placeholderNode, placeholderObject)]

            typeMaster = self._placeholderMaster(placeholderNode.attrib.get("type", "body"))

            nameStyle = self.styleObject[typeMaster] if typeMaster in self.styleObject else self.styleOther

        if nameStyle in placeholderObject["style"]:
            styleNodeList.append(placeholderObject["style"][nameStyle])

        styleNodeList.append(placeholderObject["default"])

        nodeList = [propertyNode] + [styleNode.find(f"{{{namespaceDrawing}}}lvl{level + 1}pPr") for styleNode in styleNodeList if styleNode is not None]

        return [node for node in nodeList if node is not None]

    def _levelChildFind(self, nodeList, tagList):
        for a in range(len(nodeList)):
            childList = [node for node in nodeList[a] if xmlNodeTag(node) in tagList]

            if len(childList) > 0:
                return childList[0]

        return None

    def _fontInherit(self, nodeList, tag):
        for a in range(len(nodeList)):
            fontNode = nodeList[a].find(f"{{{namespaceDrawing}}}defRPr/{{{namespaceDrawing}}}{tag}") if xmlNodeTag(nodeList[a]) != "pPr" else None

            if fontNode is not None:
                return fontNode.attrib.get("typeface", "").casefold()

        return ""

    def _markerText(self, paragraphNode, nodeList, counterObject):
        propertyNode = paragraphNode.find(f"{{{namespaceDrawing}}}pPr")

        bulletNode = self._levelChildFind(nodeList, self.tagBulletList)

        numberNode = bulletNode if bulletNode is not None and xmlNodeTag(bulletNode) == "buAutoNum" else None
        characterNode = bulletNode if bulletNode is not None and xmlNodeTag(bulletNode) == "buChar" else None

        level = int(propertyNode.attrib.get("lvl", "0")) if propertyNode is not None else 0

        match = re.fullmatch(self.patternNumber, numberNode.attrib.get("type", "")) if numberNode is not None else None

        for levelOther in list(counterObject):
            if levelOther > level or (levelOther == level and match is None):
                counterObject.pop(levelOther)

        if match is None and characterNode is None:
            return textBullet if bulletNode is not None and xmlNodeTag(bulletNode) == "buBlip" else ""

        if match is None:
            fontNode = self._levelChildFind(nodeList, ["buFont"])

            font = fontNode.attrib.get("typeface", "").casefold() if fontNode is not None else ""

            text = symbolText(characterNode.attrib.get("char", ""), font) if font in symbolObject else characterNode.attrib.get("char", "")

            return "".join(character for character in text if unicodedata.category(character) != "Co").strip()

        if level in counterObject and counterObject[level]["type"] == match.group(0):
            counterObject[level]["value"] += 1
        else:
            counterObject[level] = {"type": match.group(0), "value": int(numberNode.attrib.get("startAt", "1"))}

        return self.numberSuffixObject[match.group(2)].replace("%", numberMarker(counterObject[level]["value"], self.numberFormatObject[match.group(1)], ""))

    def _shapeText(self, shapeNode, transformObject, placeholderObject):
        itemList = []

        placeholderNode = shapeNode.find(f"{{{self.namespace}}}nvSpPr/{{{self.namespace}}}nvPr/{{{self.namespace}}}ph")

        placeholderType = placeholderNode.attrib.get("type", "body") if placeholderNode is not None else ""

        bboxList = self._boxBuild(shapeNode.find(f"{{{self.namespace}}}spPr/{{{namespaceDrawing}}}xfrm"), transformObject)

        if bboxList is None and placeholderNode is not None:
            bboxList = self._placeholderBox(placeholderNode, placeholderObject)

        textBodyNode = shapeNode.find(f"{{{self.namespace}}}txBody")

        if textBodyNode is None or placeholderType in self.placeholderSkipList:
            return self._regionBuild(labelText, bboxList, itemList)

        counterObject = {}

        for paragraphNode in textBodyNode:
            if xmlNodeTag(paragraphNode) != "p":
                continue

            nodeList = self._levelNodeList(paragraphNode, textBodyNode, placeholderNode, placeholderObject)

            fontLatin = self._fontInherit(nodeList, "latin")
            fontSymbol = self._fontInherit(nodeList, "sym")

            if fontLatin in symbolObject or fontSymbol in symbolObject:
                for runNode in paragraphNode.iter(f"{{{namespaceDrawing}}}r"):
                    drawingRunSymbolWrite(runNode, fontLatin, fontSymbol)

            text = xmlParagraphText(paragraphNode, characterDrawingObject, "")

            if text != "":
                text = f"{self._markerText(paragraphNode, nodeList, counterObject)} {text}".strip()

            if text != "" and placeholderType in self.placeholderTitleList:
                itemList.append({"kind": "title", "label": labelTitle, "level": 1, "text": text})
            elif text != "":
                itemList.append({"kind": "text", "label": labelText, "text": text})

        return self._regionBuild(labelText, bboxList, itemList)

    def _tableBuild(self, tableNode):
        cellList = []

        rowNodeList = [node for node in tableNode if xmlNodeTag(node) == "tr"]

        countColumn = 0

        for a in range(len(rowNodeList)):
            cellNodeList = [node for node in rowNodeList[a] if xmlNodeTag(node) == "tc"]

            countColumn = max(countColumn, len(cellNodeList))

            for b in range(len(cellNodeList)):
                if cellNodeList[b].attrib.get("hMerge", "") == "1" or cellNodeList[b].attrib.get("vMerge", "") == "1":
                    continue

                textList = [xmlParagraphText(paragraphNode, characterDrawingObject, "") for paragraphNode in cellNodeList[b].iter(f"{{{namespaceDrawing}}}p")]

                cellList.append({"row": a, "column": b, "rowSpan": int(cellNodeList[b].attrib.get("rowSpan", "1")), "columnSpan": int(cellNodeList[b].attrib.get("gridSpan", "1")), "text": " ".join(text for text in textList if text != "")})

        if len([cellObject for cellObject in cellList if cellObject["text"] != ""]) == 0:
            return []

        return [{"kind": "table", "label": labelTable, "rowList": gridRowList(cellList, len(rowNodeList), countColumn)}]

    def _frameBuild(self, frameNode, pathObject, zipFile, transformObject):
        itemList = []

        tableNode = frameNode.find(f".//{{{namespaceDrawing}}}tbl")
        chartNode = frameNode.find(f".//{{{namespaceChart}}}chart")

        relationshipId = chartNode.attrib.get(f"{{{namespaceRelationship}}}id", "") if chartNode is not None else ""

        if tableNode is not None:
            itemList = self._tableBuild(tableNode)
        elif relationshipId in pathObject:
            itemList = xmlChartItemList(xmlRootBuild(pathObject[relationshipId]["path"], zipFile))

        return self._regionBuild(labelTable, self._boxBuild(frameNode.find(f"{{{self.namespace}}}xfrm"), transformObject), itemList)

    def _shapeBuild(self, containerNode, transformObject, placeholderObject, pathObject, zipFile):
        resultList = []

        for node in containerNode:
            tag = xmlNodeTag(node)

            if tag == "sp":
                resultList.append(self._shapeText(node, transformObject, placeholderObject))
            elif tag == "graphicFrame":
                resultList.append(self._frameBuild(node, pathObject, zipFile, transformObject))
            elif tag == "grpSp":
                resultList += self._shapeBuild(node, self._groupTransform(node, transformObject), placeholderObject, pathObject, zipFile)
            elif tag in self.tagChoiceList:
                resultList += self._shapeBuild(node, transformObject, placeholderObject, pathObject, zipFile)

        return [regionObject for regionObject in resultList if len(regionObject["itemList"]) > 0]

    def _commentBuild(self, pathObject, zipFile, authorObject, count):
        resultList = []

        for relationshipId in pathObject:
            rootNode = xmlRootBuild(pathObject[relationshipId]["path"], zipFile) if pathObject[relationshipId]["type"].endswith("/comments") else None

            if rootNode is None:
                continue

            for node in rootNode.iter():
                if xmlNodeTag(node) not in self.tagCommentList:
                    continue

                textList = [childNode.text for childNode in node if xmlNodeTag(childNode) == "text" and childNode.text is not None]

                for bodyNode in node:
                    if xmlNodeTag(bodyNode) == "txBody":
                        textList += [xmlParagraphText(paragraphNode, characterDrawingObject, "") for paragraphNode in bodyNode.iter(f"{{{namespaceDrawing}}}p")]

                text = " ".join(" ".join(textList).split())

                author = authorObject[node.attrib.get("authorId", "")] if node.attrib.get("authorId", "") in authorObject else ""

                if text != "":
                    resultList.append({"kind": "text", "label": labelText, "text": noteText(f"{markComment}{count + len(resultList) + 1}", author, text)})

        return resultList

    def _noteBuild(self, pathObject, zipFile):
        resultList = []

        for relationshipId in pathObject:
            noteRootNode = xmlRootBuild(pathObject[relationshipId]["path"], zipFile) if pathObject[relationshipId]["type"].endswith("/notesSlide") else None

            if noteRootNode is None:
                continue

            drawingSymbolWrite(noteRootNode)

            for shapeNode in noteRootNode.iter(f"{{{self.namespace}}}sp"):
                placeholderNode = shapeNode.find(f"{{{self.namespace}}}nvSpPr/{{{self.namespace}}}nvPr/{{{self.namespace}}}ph")

                if placeholderNode is None or placeholderNode.attrib.get("type", "body") != "body":
                    continue

                for paragraphNode in shapeNode.iter(f"{{{namespaceDrawing}}}p"):
                    text = xmlParagraphText(paragraphNode, characterDrawingObject, "")

                    if text != "":
                        resultList.append({"kind": "text", "label": labelText, "text": text})

        return resultList

    def execute(self, fileInput):
        resultList = []

        zipFile = zipfile.ZipFile(fileInput)

        authorObject = self._authorBuild(zipFile)

        countComment = 0

        pathSlideList = self._slideBuild(zipFile)

        styleDefaultNode = xmlRootBuild("ppt/presentation.xml", zipFile).find(f"{{{self.namespace}}}defaultTextStyle")

        for a in range(len(pathSlideList)):
            pathObject = xmlRelationshipBuild(pathSlideList[a], zipFile)

            rootNode = xmlRootBuild(pathSlideList[a], zipFile)

            xmlFallbackRemove(rootNode)

            drawingSymbolWrite(rootNode)

            self.latex.execute(rootNode)

            treeNode = rootNode.find(f"{{{self.namespace}}}cSld/{{{self.namespace}}}spTree")

            regionList = self._shapeBuild(treeNode, None, self._placeholderBuild(styleDefaultNode, pathObject, zipFile), pathObject, zipFile)

            regionList = [regionObject for regionObject in regionList if regionObject["bbox"] is None] + self.order.execute([regionObject for regionObject in regionList if regionObject["bbox"] is not None], [])

            for b in range(len(regionList)):
                resultList += regionList[b]["itemList"]

            commentList = self._commentBuild(pathObject, zipFile, authorObject, countComment)

            countComment += len(commentList)

            resultList += commentList

            resultList += self._noteBuild(pathObject, zipFile)

        zipFile.close()

        return resultList

    def __init__(self, order, latex):
        self.order = order
        self.latex = latex

        self.namespace = "http://schemas.openxmlformats.org/presentationml/2006/main"

        self.authorTypeList = ["commentAuthors", "authors"]
        self.tagCommentList = ["cm", "reply"]

        self.tagChoiceList = ["AlternateContent", "Choice"]

        self.placeholderSkipList = ["sldNum", "dt", "ftr"]
        self.placeholderTitleList = ["title", "ctrTitle"]
        self.placeholderMasterObject = {"ctrTitle": "title", "subTitle": "body", "obj": "body"}

        self.styleObject = {"title": "titleStyle", "body": "bodyStyle"}
        self.styleOther = "otherStyle"

        self.tagBulletList = ["buNone", "buChar", "buAutoNum", "buBlip"]

        self.patternNumber = r"(arabic|alphaLc|alphaUc|romanLc|romanUc)(Period|ParenR|ParenBoth|Plain)"

        self.numberFormatObject = {"arabic": "decimal", "alphaLc": "lowerLetter", "alphaUc": "upperLetter", "romanLc": "lowerRoman", "romanUc": "upperRoman"}
        self.numberSuffixObject = {"Period": "%.", "ParenR": "%)", "ParenBoth": "(%)", "Plain": "%"}
