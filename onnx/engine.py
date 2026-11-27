import sys
import os
import json
import time
import zipfile
import subprocess
import math
import numpy
import cv2
import copy
import re
import collections
import unicodedata

sys.dont_write_bytecode = True

# Source
import primitive
import raster
import layout
import field
import region
import cell
import table
import structure
import order
import paragraph
import hyphen
import spell
import outline
import markdown
import latex
import package
import docx
import xlsx
import pptx
from helper import onnxMemoryRelease, textJoin, sizeDominant, wordKey, wideCheck, wideTextCheck, imageInkBuild, boxCenterInsideCheck, boxIntersection, boxExpand, labelGraphicList, levelLineOverlap, levelSpaceWord, levelSpaceGap, labelTable, labelForm, labelFormula, labelFormulaInline, labelFootnote, labelTitleObject, labelHeader, characterHyphenMark, labelOptionList

class Engine:
    def _extensionCategory(self, extension):
        for category in self.extensionObject:
            if extension in self.extensionObject[category]:
                return category

        return ""

    def _boxList(self, pageObject):
        resultList = []

        textList = pageObject["textList"]

        if len(textList) == 0:
            return resultList

        top = min(textObject["bbox"][1] for textObject in textList) + pageObject["size"]
        bottom = max(textObject["bbox"][3] for textObject in textList) - pageObject["size"]

        for a in range(len(pageObject["shapeList"])):
            bboxList = pageObject["shapeList"][a]["bbox"]

            width = bboxList[2] - bboxList[0]
            height = bboxList[3] - bboxList[1]

            if pageObject["shapeList"][a]["isCurve"] or min(width, height) < max(width, height) * levelSpaceGap:
                continue

            isInside = len([textObject for textObject in textList if boxCenterInsideCheck(textObject["bbox"], bboxList)]) > 0
            isBeside = len([textObject for textObject in textList if (textObject["bbox"][2] <= bboxList[0] or textObject["bbox"][0] >= bboxList[2]) and (textObject["bbox"][1] + textObject["bbox"][3]) / 2 >= bboxList[1] and (textObject["bbox"][1] + textObject["bbox"][3]) / 2 <= bboxList[3]]) > 0

            if isInside and isBeside and (bboxList[1] <= top or bboxList[3] >= bottom):
                resultList.append({"bbox": bboxList, "isTop": bboxList[1] <= top, "isBottom": bboxList[3] >= bottom, "group": -1})

        return resultList

    def _boxPageList(self, pageList):
        resultList = [self._boxList(pageObject) for pageObject in pageList]

        count = 0

        for a in range(len(resultList) - 1):
            tolerance = pageList[a]["size"] * levelSpaceWord

            for b in range(len(resultList[a])):
                boxObject = resultList[a][b]

                if boxObject["isBottom"] == False:
                    continue

                for c in range(len(resultList[a + 1])):
                    boxNextObject = resultList[a + 1][c]

                    if boxNextObject["isTop"] == False or boxNextObject["group"] != -1 or abs(boxNextObject["bbox"][0] - boxObject["bbox"][0]) > tolerance or abs(boxNextObject["bbox"][2] - boxObject["bbox"][2]) > tolerance:
                        continue

                    if boxObject["group"] == -1:
                        boxObject["group"] = count

                        count += 1

                    boxNextObject["group"] = boxObject["group"]

                    break

        return [[boxObject for boxObject in boxList if boxObject["group"] != -1] for boxList in resultList]

    def _pageImage(self, resolution, numberPage, password, pathInput):
        argumentList = ["pdftoppm", "-png", "-cropbox", "-singlefile", "-r", str(resolution), "-f", str(numberPage), "-l", str(numberPage)]

        if len(password) > 0:
            argumentList = argumentList + ["-upw", password, "-opw", password]

        runObject = subprocess.run(argumentList + [pathInput], capture_output=True)

        return cv2.imdecode(numpy.frombuffer(runObject.stdout, dtype=numpy.uint8), cv2.IMREAD_COLOR)

    def _glyphTextList(self, pageObject, scale, image):
        resultList = []

        for a in range(len(pageObject["textList"])):
            textObject = pageObject["textList"][a]

            textPlain = "".join(character for character in textObject["text"] if unicodedata.category(character) != "Co")

            if textPlain.strip() != "":
                textObject["text"] = textPlain

                resultList.append(textObject)

                continue

            bboxList = textObject["bbox"]

            imageCrop = image[max(0, int(bboxList[1] * scale)):math.ceil(bboxList[3] * scale), max(0, int(bboxList[0] * scale)):math.ceil(bboxList[2] * scale)]

            if pageObject["isTurn"]:
                imageCrop = cv2.rotate(imageCrop, cv2.ROTATE_90_CLOCKWISE)

            height, width = imageCrop.shape[0:2]

            recognitionObject = self.raster.recognition.execute([[[0, 0], [width, 0], [width, height], [0, height]]], imageCrop)[0] if height > 0 and width > 0 else {"text": "", "score": 0.0}

            if recognitionObject["text"].strip() != "" and recognitionObject["score"] >= self.raster.watermark.levelScore:
                result = dict(textObject)
                result["text"] = recognitionObject["text"].strip()

                resultList.append(result)

        return resultList

    def _zoneShapeList(self, zoneList, pageObject):
        return [{"bbox": zoneObject["bbox"], "isCurve": False} for zoneObject in zoneList if zoneObject["label"] in labelOptionList and len([shapeObject for shapeObject in pageObject["shapeList"] if boxCenterInsideCheck(shapeObject["bbox"], zoneObject["bbox"])]) == 0]

    def _zoneTextList(self, zoneList, pageObject, scale, image):
        resultList = []

        for a in range(len(zoneList)):
            bboxList = zoneList[a]["bbox"]

            if zoneList[a]["label"] in labelGraphicList and len([textObject for textObject in pageObject["textList"] if boxIntersection(textObject["bbox"], bboxList) > 0]) == 0 and len([zoneObject for zoneObject in zoneList[0:a] if zoneObject["label"] in labelGraphicList and boxIntersection(zoneObject["bbox"], bboxList) > 0]) == 0:
                resultList += [textObject for textObject in self.raster.zoneExecute(bboxList, scale, image) if textObject["size"] < min(bboxList[2] - bboxList[0], bboxList[3] - bboxList[1]) * levelLineOverlap]

        return resultList

    def _guardCount(self, text):
        return collections.Counter(str(unicodedata.decimal(character)) if character.isdecimal() else character for character in text if character.isdecimal() or unicodedata.category(character) == "Sc")

    def _guardCheck(self, text, textLatex):
        return self._guardCount(text) == self._guardCount(re.sub(self.latex.patternMark, "", textLatex))

    def _inkCover(self, bboxList, textList, scale, image):
        left = max(0, int(bboxList[0] * scale))
        top = max(0, int(bboxList[1] * scale))

        imageInk = imageInkBuild(image[top:int(bboxList[3] * scale), left:int(bboxList[2] * scale)])

        imageText = numpy.zeros(imageInk.shape, numpy.uint8)

        for a in range(len(textList)):
            bboxTextList = textList[a]["bbox"]

            imageText[max(0, int(bboxTextList[1] * scale) - top):max(0, int(bboxTextList[3] * scale) - top), max(0, int(bboxTextList[0] * scale) - left):max(0, int(bboxTextList[2] * scale) - left)] = 1

        rowList = numpy.flatnonzero((imageInk * (1 - imageText)).sum(axis=1))
        columnList = numpy.flatnonzero((imageInk * (1 - imageText)).sum(axis=0))

        return {
            "ratio": float((imageInk * imageText).sum()) / float(imageInk.sum()) if imageInk.sum() > 0 else 1.0,
            "bbox": [(left + int(columnList[0])) / scale, (top + int(rowList[0])) / scale, (left + int(columnList[len(columnList) - 1]) + 1) / scale, (top + int(rowList[len(rowList) - 1]) + 1) / scale] if len(rowList) > 0 else list(bboxList)
        }

    def _formulaTextList(self, pageObject, zoneList, scale, image, isRaster):
        resultList = pageObject["textList"]

        for a in range(len(zoneList)):
            if zoneList[a]["label"] != labelFormula:
                continue

            bboxList = list(zoneList[a]["bbox"])

            zoneTextList = [textObject for textObject in resultList if boxCenterInsideCheck(textObject["bbox"], bboxList)]
            numberList = [textObject for textObject in zoneTextList if len([bboxNumber for bboxNumber in zoneList[a]["numberList"] if boxCenterInsideCheck(textObject["bbox"], bboxNumber)]) > 0]

            numberIdList = [id(textObject) for textObject in numberList]

            insideList = [textObject for textObject in zoneTextList if id(textObject) not in numberIdList]

            coverObject = self._inkCover(bboxList, insideList, scale, image) if isRaster == False and len(insideList) > 0 else {"ratio": 1.0, "bbox": bboxList}

            bboxFormulaList = bboxList

            if coverObject["ratio"] < levelLineOverlap:
                numberList = numberList + insideList

                insideList = []

                bboxFormulaList = coverObject["bbox"]

            bboxPaintList = [bboxNumber for bboxNumber in zoneList[a]["numberList"] if len([textObject for textObject in numberList if boxCenterInsideCheck(textObject["bbox"], bboxNumber)]) > 0]

            text = self.latex.zoneExecute(bboxList, scale, image, bboxPaintList + [textObject["bbox"] for textObject in numberList], False)

            if text == "" or (isRaster == False and len(insideList) > 0 and self._guardCheck("".join(textObject["text"] for textObject in insideList), text) == False):
                continue

            if isRaster:
                text = self.latex.wordResolve(text, [textObject["text"] for textObject in insideList])
            elif len(insideList) == 0:
                text = self.latex.wordResolve(text, [textObject["text"] for textObject in self.raster.zoneExecute(bboxList, scale, image)])

            insideIdList = [id(textObject) for textObject in insideList]

            resultList = [textObject for textObject in resultList if id(textObject) not in insideIdList]

            for b in range(len(insideList)):
                bboxFormulaList = list(insideList[b]["bbox"]) if b == 0 else boxExpand(bboxFormulaList, insideList[b]["bbox"])

            resultList.append({"bbox": bboxFormulaList, "text": text, "size": pageObject["size"], "angle": 0, "isVertical": False, "fieldIndex": None, "alternativeList": []})

        return resultList

    def _characterBox(self, textObject, index):
        width = textObject["bbox"][2] - textObject["bbox"][0]

        return [textObject["bbox"][0] + width * textObject["positionList"][index]["start"], textObject["bbox"][1], textObject["bbox"][0] + width * textObject["positionList"][index]["end"], textObject["bbox"][3]]

    def _textPart(self, textObject, indexStart, indexEnd):
        text = textObject["text"][indexStart:indexEnd]

        indexStart += len(text) - len(text.lstrip())
        indexEnd -= len(text) - len(text.rstrip())

        if indexStart >= indexEnd:
            return []

        bboxList = boxExpand(self._characterBox(textObject, indexStart), self._characterBox(textObject, indexEnd - 1))

        width = bboxList[2] - bboxList[0] if bboxList[2] != bboxList[0] else 1

        positionList = [{"text": textObject["positionList"][a]["text"], "start": (self._characterBox(textObject, a)[0] - bboxList[0]) / width, "end": (self._characterBox(textObject, a)[2] - bboxList[0]) / width} for a in range(indexStart, indexEnd)]

        partObject = dict(textObject)
        partObject["bbox"] = bboxList
        partObject["text"] = textObject["text"][indexStart:indexEnd]
        partObject["positionList"] = positionList

        if "alternativeList" in textObject:
            partObject["alternativeList"] = textObject["alternativeList"][indexStart:indexEnd]

        return [partObject]

    def _fontFind(self, textObject):
        return textObject["font"] if "font" in textObject else None

    def _tokenList(self, textList, cutList):
        resultList = []

        for a in range(len(cutList)):
            textObject = textList[cutList[a]["index"]]

            start = cutList[a]["start"]

            for b in range(cutList[a]["start"], cutList[a]["end"] + 1):
                if b < cutList[a]["end"] and textObject["text"][b].strip() != "":
                    continue

                if b > start:
                    resultList.append({"index": cutList[a]["index"], "start": start, "end": b, "bbox": boxExpand(self._characterBox(textObject, start), self._characterBox(textObject, b - 1)), "text": textObject["text"][start:b], "size": textObject["size"], "font": self._fontFind(textObject)})

                start = b + 1

        resultList.sort(key=lambda tokenObject: tokenObject["bbox"][0])

        return resultList

    def _fontSide(self, textList, tokenObject, isLeft):
        textObject = textList[tokenObject["index"]]

        if (textObject["text"][0:tokenObject["start"]] if isLeft else textObject["text"][tokenObject["end"]:]).strip() != "":
            return self._fontFind(textObject)

        centerY = (tokenObject["bbox"][1] + tokenObject["bbox"][3]) / 2

        sideList = [sideObject for sideObject in textList if "positionList" in sideObject and centerY >= sideObject["bbox"][1] and centerY <= sideObject["bbox"][3] and (sideObject["bbox"][2] <= tokenObject["bbox"][0] if isLeft else sideObject["bbox"][0] >= tokenObject["bbox"][2])]

        if len(sideList) == 0:
            return ""

        return self._fontFind(max(sideList, key=lambda sideObject: sideObject["bbox"][2]) if isLeft else min(sideList, key=lambda sideObject: sideObject["bbox"][0]))

    def _wordCheck(self, tokenObject, tokenNextObject, font):
        characterList = [character for character in tokenObject["text"] if unicodedata.category(character)[0] != "P"]

        return len(characterList) > 1 and len([character for character in characterList if character.isalpha() == False]) == 0 and tokenObject["font"] != None and tokenObject["font"] == font and tokenObject["size"] == tokenNextObject["size"]

    def _raisedCheck(self, textObject, textPreviousObject):
        return textObject["size"] < textPreviousObject["size"] and textObject["bbox"][3] < textPreviousObject["bbox"][3]

    def _wordPeel(self, textList, tokenList, noteList):
        resultList = []

        fontLeft = self._fontSide(textList, tokenList[0], True)
        fontRight = self._fontSide(textList, tokenList[len(tokenList) - 1], False)

        while len(tokenList) > 1 and self._wordCheck(tokenList[0], tokenList[1], fontLeft):
            resultList.append(tokenList.pop(0))

        if len(tokenList) > 1 and tokenList[len(tokenList) - 1]["text"] in noteList and self._raisedCheck(tokenList[len(tokenList) - 1], tokenList[len(tokenList) - 2]):
            resultList.append(tokenList.pop(len(tokenList) - 1))

        while len(tokenList) > 1 and self._wordCheck(tokenList[len(tokenList) - 1], tokenList[len(tokenList) - 2], fontRight):
            resultList.append(tokenList.pop(len(tokenList) - 1))

        return resultList

    def _noteList(self, zoneList, textList):
        labelList = []

        for a in range(len(zoneList)):
            insideList = [textObject for textObject in textList if zoneList[a]["label"] == labelFootnote and boxCenterInsideCheck(textObject["bbox"], zoneList[a]["bbox"])]

            if len(insideList) > 0:
                labelList.append(min(insideList, key=lambda textObject: (textObject["bbox"][1], textObject["bbox"][0]))["text"])

        raisedList = []

        for a in range(len(textList)):
            if textList[a]["text"] not in labelList:
                continue

            centerY = (textList[a]["bbox"][1] + textList[a]["bbox"][3]) / 2

            previousList = [textObject for textObject in textList if textObject["bbox"][2] <= textList[a]["bbox"][0] and centerY >= textObject["bbox"][1] and centerY <= textObject["bbox"][3]]

            if len(previousList) > 0 and self._raisedCheck(textList[a], max(previousList, key=lambda textObject: textObject["bbox"][2])):
                raisedList.append(textList[a]["text"])

        return [text for text in labelList if text.isdecimal() and raisedList.count(text) == 1]

    def _inkRange(self, textObject, indexStart, indexEnd, scale, imageInk):
        bboxList = boxExpand(self._characterBox(textObject, indexStart), self._characterBox(textObject, indexEnd - 1))

        top = max(0, int(bboxList[1] * scale))

        rowList = numpy.flatnonzero(imageInk[top:int(bboxList[3] * scale), max(0, int(bboxList[0] * scale)):int(bboxList[2] * scale) + 1].sum(axis=1))

        return [top + int(rowList[0]), top + int(rowList[len(rowList) - 1])] if len(rowList) > 0 else []

    def _inkRaisedCheck(self, textObject, indexStart, indexEnd, scale, imageInk):
        rangeList = self._inkRange(textObject, indexStart, indexEnd, scale, imageInk)

        bottomList = []

        for a in range(len(textObject["text"])):
            rangeOtherList = self._inkRange(textObject, a, a + 1, scale, imageInk) if textObject["text"][a].strip() != "" and (a < indexStart or a >= indexEnd) else []

            if len(rangeOtherList) > 0:
                bottomList.append(rangeOtherList[1])

        if len(rangeList) == 0 or len(bottomList) == 0:
            return False

        return sorted(bottomList)[int(len(bottomList) / 2)] - rangeList[1] > (rangeList[1] - rangeList[0] + 1) * levelLineOverlap

    def _noteImageList(self, zoneList, textList, scale, imageInk):
        resultList = []

        labelList = []

        for a in range(len(zoneList)):
            insideList = [textObject for textObject in textList if zoneList[a]["label"] == labelFootnote and boxCenterInsideCheck(textObject["bbox"], zoneList[a]["bbox"])]

            match = re.match(self.patternNumber, min(insideList, key=lambda textObject: (textObject["bbox"][1], textObject["bbox"][0]))["text"]) if len(insideList) > 0 else None

            if match is not None and match.group(0) not in labelList:
                labelList.append(match.group(0))

        for a in range(len(labelList)):
            count = 0

            for b in range(len(textList)):
                textObject = textList[b]

                if "font" in textObject or "positionList" not in textObject or len(textObject["positionList"]) != len(textObject["text"]):
                    continue

                for match in re.finditer(self.patternNumber, textObject["text"]):
                    if match.group(0) == labelList[a] and match.start() > 0 and self._inkRaisedCheck(textObject, match.start(), match.end(), scale, imageInk):
                        count += 1

            if count == 1:
                resultList.append(labelList[a])

        return resultList

    def _noteCut(self, textList, tokenList, noteList, scale, imageInk):
        tokenObject = tokenList[len(tokenList) - 1]

        textObject = textList[tokenObject["index"]]

        for a in range(len(noteList)):
            start = tokenObject["end"] - len(noteList[a])

            if "font" in textObject or tokenObject["text"].endswith(noteList[a]) == False or start <= tokenObject["start"] or self._inkRaisedCheck(textObject, start, tokenObject["end"], scale, imageInk) == False:
                continue

            bboxList = boxExpand(self._characterBox(textObject, start), self._characterBox(textObject, tokenObject["end"] - 1))

            tokenObject["end"] = start
            tokenObject["text"] = textObject["text"][tokenObject["start"]:start]
            tokenObject["bbox"] = boxExpand(self._characterBox(textObject, tokenObject["start"]), self._characterBox(textObject, start - 1))

            return [bboxList]

        return []

    def _inlineTextList(self, pageObject, zoneList, scale, image):
        resultList = pageObject["textList"]

        noteList = self._noteList(zoneList, resultList)

        imageInk = imageInkBuild(image)

        noteImageList = self._noteImageList(zoneList, resultList, scale, imageInk)

        for a in range(len(zoneList)):
            if zoneList[a]["label"] != labelFormulaInline:
                continue

            bboxList = zoneList[a]["bbox"]

            cutList = []

            for b in range(len(resultList)):
                textObject = resultList[b]

                if "positionList" not in textObject or len(textObject["positionList"]) != len(textObject["text"]) or textObject["angle"] != 0 or textObject["isVertical"]:
                    continue

                indexList = [c for c in range(len(textObject["positionList"])) if textObject["positionList"][c]["text"].strip() != "" and boxCenterInsideCheck(self._characterBox(textObject, c), bboxList)]

                if len(indexList) > 0:
                    cutList.append({"index": b, "start": indexList[0], "end": indexList[len(indexList) - 1] + 1})

            if len(cutList) == 0:
                continue

            tokenList = self._tokenList(resultList, cutList)

            wordList = self._wordPeel(resultList, tokenList, noteList)

            text = self.latex.zoneExecute(bboxList, scale, image, [tokenObject["bbox"] for tokenObject in wordList] + self._noteCut(resultList, tokenList, noteImageList, scale, imageInk), True)

            if text == "" or self.latex.structureCheck(text) == False or self._guardCheck("".join(tokenObject["text"] for tokenObject in tokenList), text) == False:
                continue

            bboxInlineList = list(tokenList[0]["bbox"])

            partList = []

            indexList = sorted(set(tokenObject["index"] for tokenObject in tokenList))

            for b in range(len(indexList)):
                textObject = resultList[indexList[b]]

                start = min(tokenObject["start"] for tokenObject in tokenList if tokenObject["index"] == indexList[b])
                end = max(tokenObject["end"] for tokenObject in tokenList if tokenObject["index"] == indexList[b])

                bboxInlineList = boxExpand(boxExpand(bboxInlineList, self._characterBox(textObject, start)), self._characterBox(textObject, end - 1))

                partList += self._textPart(textObject, 0, start) + self._textPart(textObject, end, len(textObject["text"]))

            cutIdList = [id(resultList[index]) for index in indexList]

            size = resultList[indexList[0]]["size"]

            resultList = [textObject for textObject in resultList if id(textObject) not in cutIdList] + partList

            resultList.append({"bbox": bboxInlineList, "text": text, "size": size, "angle": 0, "isVertical": False, "fieldIndex": None, "alternativeList": []})

        return resultList

    def _regionList(self, pageObject, zoneList, image, scale, boxList):
        pageObject["textList"] = self.field.execute(pageObject, zoneList, image, scale)

        return self.region.execute([zoneObject for zoneObject in zoneList if zoneObject["label"] not in labelOptionList and zoneObject["label"] != labelFormulaInline] + [{"label": labelForm, "score": 0.0, "bbox": boxObject["bbox"]} for boxObject in boxList], pageObject)

    def _tableResolve(self, regionList, image, scale, ruleList):
        for a in range(len(regionList)):
            regionObject = regionList[a]

            if regionObject["label"] == labelTable and len(regionObject["itemList"]) > 0:
                boxCellList = self.cell.execute(image, scale, regionObject["bbox"], regionObject["itemList"], ruleList)

                regionObject["rowList"] = self.table.execute(image, scale, regionObject["bbox"], boxCellList, regionObject["itemList"], self.structure.execute(image, scale, regionObject["bbox"]), ruleList)

    def _regionText(self, regionObject):
        result = ""

        for a in range(len(regionObject["lineList"])):
            result = textJoin(result, regionObject["lineList"][a]["text"])

        return result

    def _regionWrite(self, regionObject, numberPage, group):
        if len(regionObject["rowList"]) > 0:
            return [{"kind": "table", "label": regionObject["label"], "page": numberPage, "group": group, "bbox": regionObject["bbox"], "rowList": regionObject["rowList"]}]

        resultList = []

        text = self._regionText(regionObject)

        if text == "":
            return resultList

        if regionObject["label"] in labelTitleObject:
            resultList.append({"kind": "title", "label": regionObject["label"], "page": numberPage, "group": group, "bbox": regionObject["bbox"], "level": labelTitleObject[regionObject["label"]], "text": text, "size": sizeDominant(regionObject["itemList"])})
        else:
            resultList.append({"kind": "text", "label": regionObject["label"], "page": numberPage, "group": group, "bbox": regionObject["bbox"], "text": text, "lineList": regionObject["lineList"]})

        return resultList

    def _groupFind(self, boxList, regionObject):
        for a in range(len(boxList)):
            if boxCenterInsideCheck(regionObject["bbox"], boxList[a]["bbox"]):
                return boxList[a]["group"]

        return -1

    def _groupResolve(self, itemList):
        resultList = []

        pageObject = {}
        indexObject = {}

        for a in range(len(itemList)):
            group = itemList[a]["group"]

            if group != -1 and group not in pageObject:
                pageObject[group] = itemList[a]["page"]

            if group != -1 and itemList[a]["page"] == pageObject[group]:
                indexObject[group] = a

        for a in range(len(itemList)):
            group = itemList[a]["group"]

            if group != -1 and itemList[a]["page"] != pageObject[group]:
                continue

            resultList.append(itemList[a])

            if group != -1 and indexObject[group] == a:
                resultList += [itemObject for itemObject in itemList if itemObject["group"] == group and itemObject["page"] != pageObject[group]]

        return resultList

    def _hyphenResolve(self, itemList):
        textObjectList = []

        for a in range(len(itemList)):
            if itemList[a]["kind"] == "table":
                textObjectList += [cellObject for rowObject in itemList[a]["rowList"] for cellObject in rowObject]
            else:
                textObjectList.append(itemList[a])

        wordList = set()

        for a in range(len(textObjectList)):
            tokenList = textObjectList[a]["text"].split(" ")

            for b in range(len(tokenList)):
                if characterHyphenMark not in tokenList[b]:
                    wordList.add(wordKey(tokenList[b]))

        for a in range(len(textObjectList)):
            textObjectList[a]["text"] = self.hyphen.execute(textObjectList[a]["text"], wordList)

        return itemList

    def _resultWrite(self, pathOutput, itemList, pathInput, timeStart):
        with open(f"{pathOutput}result.md", "w", encoding="utf-8") as file:
            file.write(self.markdown.execute(itemList))

        with zipfile.ZipFile(f"{pathOutput}result.zip", "w") as zipFile:
            zipFile.write(f"{pathOutput}result.md", "result.md", zipfile.ZIP_DEFLATED)

        print(f"\nengine.py - Time: {round(time.perf_counter() - timeStart, 3)} - {os.path.basename(pathInput)}")

        return {"response": {"state": "ok", "message": "Task completed."}}

    def _extensionAllowed(self):
        resultObject = {"image": [], "pdf": [], "office": []}

        mimeTypeList = json.loads(os.environ["MS_FDE_MIME_TYPE"])

        for a in range(len(mimeTypeList)):
            if mimeTypeList[a].startswith("image/"):
                resultObject["image"].append(f".{mimeTypeList[a].split('/')[1]}")
            elif mimeTypeList[a] == "application/pdf":
                resultObject["pdf"].append(".pdf")
            elif mimeTypeList[a] in self.mimeTypeOfficeObject:
                resultObject["office"].append(self.mimeTypeOfficeObject[mimeTypeList[a]])

        return resultObject

    def execute(self, pathInput, pathOutput, job, password):
        timeStart = time.perf_counter()

        extension = os.path.splitext(pathInput)[1].lower()

        category = self._extensionCategory(extension)

        if category == "":
            return {"response": {"state": "ko", "message": "Extension not supported."}}

        os.makedirs(pathOutput, exist_ok=True)

        if job["isCancel"]:
            return {"response": {"state": "ko", "message": "Job cancelled."}}

        if category == "office":
            packageObject = self.package.execute(pathInput, password)

            if packageObject["message"] != "":
                return {"response": {"state": "ko", "message": packageObject["message"]}}

            return self._resultWrite(pathOutput, self.readerObject[extension].execute(packageObject["file"]), pathInput, timeStart)

        resultObject = self.primitive.pdfExecute(pathInput, password) if category == "pdf" else {"message": "", "pageList": [{"size": 0, "textList": [], "fieldList": [], "shapeList": [], "ruleList": []}]}

        if resultObject["message"] != "":
            return {"response": {"state": "ko", "message": resultObject["message"]}}

        if len(resultObject["pageList"]) == 0:
            return {"response": {"state": "ko", "message": "File not readable."}}

        itemList = []

        boxPageList = self._boxPageList(resultObject["pageList"])

        for a in range(len(resultObject["pageList"])):
            if job["isCancel"]:
                return {"response": {"state": "ko", "message": "Job cancelled."}}

            pageObject = resultObject["pageList"][a]

            isRaster = len(pageObject["textList"]) == 0

            image = self._pageImage(self.resolution, a + 1, password, pathInput) if category == "pdf" else cv2.imread(pathInput)

            if image is None:
                return {"response": {"state": "ko", "message": "File not readable."}}

            scale = self.resolution / self.pointInch

            if isRaster == False and pageObject["isTurn"]:
                image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)

            if isRaster == False:
                pageObject["textList"] = self._glyphTextList(pageObject, scale, image)

            if isRaster:
                rasterObject = self.raster.execute(image, scale)

                textPage = "".join(textObject["text"].replace(" ", "") for textObject in rasterObject["pageObject"]["textList"])

                if category == "pdf" and rasterObject["sizeLine"] > 0 and rasterObject["sizeLine"] < self.raster.recognition.imageHeightModel and wideTextCheck(textPage):
                    self.raster.textExecute(self._pageImage(math.ceil(self.resolution * self.raster.recognition.imageHeightModel / rasterObject["sizeLine"]), a + 1, password, pathInput), rasterObject, scale)

                image = rasterObject["image"]
                pageObject = rasterObject["pageObject"]

            zoneList = self.layout.execute(image, scale)

            if isRaster:
                pageObject["shapeList"] += self._zoneShapeList(zoneList, pageObject)
            else:
                pageObject["textList"] += self._zoneTextList(zoneList, pageObject, scale, image)

            if isRaster:
                textList = copy.deepcopy(pageObject["textList"])

                self.spell.execute(textList, self.order.execute(self._regionList(pageObject, zoneList, image, scale, boxPageList[a]), pageObject["ruleList"]))

                pageObject["textList"] = textList

            pageObject["textList"] = self._formulaTextList(pageObject, zoneList, scale, image, isRaster)

            pageObject["textList"] = self._inlineTextList(pageObject, zoneList, scale, image)

            regionList = self._regionList(pageObject, zoneList, image, scale, boxPageList[a])

            self._tableResolve(regionList, image, scale, pageObject["ruleList"])

            for b in range(len(regionList)):
                if regionList[b]["label"] == labelHeader:
                    itemList += self._regionWrite(regionList[b], a + 1, -1)

            regionList = self.order.execute(regionList, pageObject["ruleList"])

            for b in range(len(regionList)):
                itemList += self._regionWrite(regionList[b], a + 1, self._groupFind(boxPageList[a], regionList[b]))

        itemList = self.outline.execute(self._hyphenResolve([itemObject for itemObject in self.paragraph.execute(self._groupResolve(itemList)) if itemObject["label"] != labelHeader]))

        onnxMemoryRelease(self.raster.orientation.onnxSession)

        return self._resultWrite(pathOutput, itemList, pathInput, timeStart)

    def __init__(self):
        self.mimeTypeOfficeObject = {
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
            "application/vnd.ms-excel.sheet.macroEnabled.12": ".xlsm",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx"
        }

        self.extensionObject = self._extensionAllowed()

        self.primitive = primitive.Primitive()
        self.raster = raster.Raster()
        self.layout = layout.Layout()
        self.field = field.Field()
        self.region = region.Region()
        self.cell = cell.Cell()
        self.table = table.Table()
        self.structure = structure.Structure()
        self.order = order.Order()
        self.paragraph = paragraph.Paragraph()
        self.hyphen = hyphen.Hyphen()
        self.spell = spell.Spell(self.hyphen)
        self.outline = outline.Outline()
        self.markdown = markdown.Markdown()

        self.latex = latex.Latex()
        self.package = package.Package()

        self.readerObject = {".docx": docx.Docx(self.latex), ".xlsx": xlsx.Xlsx(self.latex), ".pptx": pptx.Pptx(self.order, self.latex)}
        self.readerObject[".xlsm"] = self.readerObject[".xlsx"]

        self.patternNumber = r"\d+"

        self.resolution = 150
        self.pointInch = 72

        cv2.setUseOptimized(True)
        cv2.setNumThreads(0)
