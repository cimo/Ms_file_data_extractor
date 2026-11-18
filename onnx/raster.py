import sys
import subprocess
import cv2
import numpy

sys.dont_write_bytecode = True

# Source
import pdf
from helper import boxFromPointList, centerPointCalculate, imageInkBuild, boxDebugWrite, astWrite, detectionBoxBuild, levelSpaceGap, textBullet

class Raster:
    def astBuild(self, pathOutput, pageObject):
        astPage = self.layout.execute(pathOutput, pageObject["image"], pageObject["number"])

        return {"astPage": astPage, "tablePageList": self.table.execute(astPage, pageObject["image"])}

    def pageAssemble(self, astPage, itemPageList, ruleList, tablePageList, pageObject, pathOutput, countTable):
        self.layout.itemOrder(astPage, itemPageList, ruleList)

        self.table.orderAssign(astPage, tablePageList)

        self.layout.mediaWrite(astPage, pageObject["image"], pathOutput)

        self.table.cellRefine(tablePageList, itemPageList, astPage["direction"], pageObject["image"])

        self.table.textAssign(tablePageList, itemPageList, astPage["direction"])

        self.table.debugWrite(tablePageList, pageObject["image"], itemPageList, pathOutput, pageObject["number"], countTable)

        return self.table.resultTableBuild(tablePageList, countTable, pageObject["number"])

    def moduleCheck(self, pageObject, tablePageList, bboxList):
        imageHeight, imageWidth = pageObject["image"].shape[0:2]

        return self.module.pageCheck(tablePageList, imageHeight * imageWidth, bboxList)

    def moduleBuild(self, detectionList, image, watermarkObject, numberPage, countStart, pathOutput):
        resultObject = self.module.itemImageBuild(detectionList, image, self.ocr.recognition, watermarkObject, numberPage)

        itemList = []
        bboxDebugList = []

        for a in range(len(resultObject["itemList"])):
            bboxList = [int(round(value)) for value in resultObject["itemList"][a]["bbox"]]

            itemList.append({
                "id": countStart + len(itemList) + 1,
                "page": numberPage,
                "bbox": bboxList,
                "centerPoint": centerPointCalculate(bboxList),
                "text": resultObject["itemList"][a]["text"]
            })

            bboxDebugList.append(bboxList)

        if self.isDebug:
            boxDebugWrite(image, bboxDebugList, f"{pathOutput}debug/ocr/{numberPage}.jpg")

        return {"itemList": itemList, "text": self.module.execute(resultObject["itemList"], resultObject["ringList"], resultObject["lineObject"], [], numberPage)}

    def watermarkApply(self, pageObject, pathOutput):
        detectionList = self.ocr.boxDetect(pageObject["image"])

        watermarkObject = self.watermark.execute(detectionBoxBuild(detectionList), pageObject["image"])

        if not watermarkObject["isFound"]:
            return {"detectionList": detectionList, "watermarkObject": watermarkObject}

        image = watermarkObject["image"]

        if self.isDebug:
            imageDebug = pageObject["image"].copy()
            imageDebug[watermarkObject["zone"] > 0] = (imageDebug[watermarkObject["zone"] > 0] * 0.5 + numpy.array([0, 0, 255]) * 0.5).astype(numpy.uint8)

            cv2.imwrite(f"{pathOutput}debug/watermark/{pageObject['number']}_zone.jpg", imageDebug)
            cv2.imwrite(f"{pathOutput}debug/watermark/{pageObject['number']}.jpg", image)

        mergeObject = self.watermark.detectionMerge(detectionList, watermarkObject["zone"], self.ocr.boxDetect(image), self.ocr.recognition, image)

        return {"detectionList": detectionList, "watermarkObject": {"isFound": True, "image": image, "isKeepList": mergeObject["isKeepList"], "detectionZoneList": mergeObject["detectionZoneList"]}}

    def detectionCheckList(self, detectionList, watermarkObject):
        if not watermarkObject["isFound"]:
            return detectionBoxBuild(detectionList)

        resultList = []

        for a in range(len(detectionList)):
            if watermarkObject["isKeepList"][a]:
                resultList.append(boxFromPointList(detectionList[a]["coordinate"]))

        return resultList + detectionBoxBuild(watermarkObject["detectionZoneList"])

    def itemOcrBuild(self, pageObject, pathOutput, tablePageList, countStart, moduleList):
        ocrObject = self.watermarkApply(pageObject, pathOutput)

        if self.moduleCheck(pageObject, tablePageList, self.detectionCheckList(ocrObject["detectionList"], ocrObject["watermarkObject"])):
            moduleObject = self.moduleBuild(ocrObject["detectionList"], pageObject["image"], ocrObject["watermarkObject"], pageObject["number"], countStart, pathOutput)

            moduleList.append({"page": pageObject["number"], "text": moduleObject["text"]})

            return moduleObject["itemList"]

        return self.ocr.execute(ocrObject["detectionList"], pageObject["image"], tablePageList, ocrObject["watermarkObject"], countStart, pageObject["number"], pathOutput)

    def ruleImageBuild(self, image):
        imageWidth = image.shape[1]

        imageRule = cv2.morphologyEx(imageInkBuild(image), cv2.MORPH_OPEN, numpy.ones((1, max(1, int(imageWidth * self.levelRuleImage))), numpy.uint8))

        count, _, statList, _ = cv2.connectedComponentsWithStats(imageRule)

        resultList = []

        for a in range(1, count):
            x, y, width, height = statList[a][0:4]

            centerY = int(y + height / 2)

            resultList.append([int(x), centerY, int(x + width), centerY])

        return resultList

    def documentBuild(self, astPageList, pathOutput, countPage, tableList, itemList, moduleList):
        self.layout.flowAssign(astPageList)

        layoutList = []

        for a in range(len(astPageList)):
            layoutList = layoutList + self.layout.resultLayoutBuild(astPageList[a], len(layoutList))

        if self.isDebug:
            astWrite(pathOutput, astPageList)

        return {
            "pageCount": countPage,
            "directionList": self.layout.directionBuild(astPageList),
            "layoutList": layoutList,
            "tableList": tableList,
            "itemList": itemList,
            "moduleList": moduleList
        }

    def __init__(self, isDebug, layout, table, ocr, module, watermark):
        self.isDebug = isDebug

        self.layout = layout
        self.table = table
        self.ocr = ocr
        self.module = module
        self.watermark = watermark

        self.levelRuleImage = 0.25

        self.image = Raster.Image(self)
        self.pdf = Raster.Pdf(self)

    class Image:
        def _pageImageBuild(self, pathInput, pathOutput):
            image = cv2.imread(pathInput)

            if image is None:
                return []

            if self.raster.isDebug:
                cv2.imwrite(f"{pathOutput}debug/page/{self.numberPageFirst}.jpg", image)

            return [{"number": self.numberPageFirst, "image": image}]

        def execute(self, pathInput, pathOutput, job):
            pageList = self._pageImageBuild(pathInput, pathOutput)

            astPageList = []
            tableList = []
            itemList = []
            moduleList = []

            for a in range(len(pageList)):
                if job["isCancel"]:
                    return {"message": "Job cancelled."}

                astObject = self.raster.astBuild(pathOutput, pageList[a])

                astPageList.append(astObject["astPage"])

                if job["isCancel"]:
                    return {"message": "Job cancelled."}

                itemPageList = self.raster.itemOcrBuild(pageList[a], pathOutput, astObject["tablePageList"], len(itemList), moduleList)

                if job["isCancel"]:
                    return {"message": "Job cancelled."}

                tableList = tableList + self.raster.pageAssemble(astObject["astPage"], itemPageList, self.raster.ruleImageBuild(pageList[a]["image"]), astObject["tablePageList"], pageList[a], pathOutput, len(tableList))
                itemList = itemList + itemPageList

            return self.raster.documentBuild(astPageList, pathOutput, len(pageList), tableList, itemList, moduleList)

        def __init__(self, raster):
            self.numberPageFirst = 1

            self.raster = raster

    class Pdf:
        def _pagePdfBuild(self, password, pathInput, pathOutput):
            argumentList = ["pdftoppm", "-jpeg", "-cropbox", "-r", self.resolution]

            if len(password) > 0:
                argumentList = argumentList + ["-upw", password, "-opw", password]

            runObject = subprocess.run(argumentList + [pathInput], capture_output=True)

            if runObject.returncode != 0:
                print(f"raster.py - pdftoppm - {runObject.stderr.decode('utf-8', 'replace').strip()}")

                return []

            byteFileList = self._pageStreamSplit(runObject.stdout)

            resultList = []

            for a in range(len(byteFileList)):
                numberPage = a + 1

                if self.raster.isDebug:
                    with open(f"{pathOutput}debug/page/{numberPage}.jpg", "wb") as file:
                        file.write(byteFileList[a])

                resultList.append({"number": numberPage, "byte": byteFileList[a]})

            return resultList

        def _modulePdfBuild(self, pageObject, pageCharObject):
            numberPage = pageObject["number"]

            scale = pageObject["image"].shape[1] / pageCharObject["width"]

            itemModuleList = self.raster.module.itemPdfBuild(pageCharObject["elementList"], scale, numberPage)

            detectionList = self.raster.ocr.boxDetect(pageObject["image"])

            ringList = self.raster.module.ringBuild(pageObject["image"], detectionList)

            lineObject = self.raster.module.lineBuild(pageObject["image"], detectionList)

            circleList = self.raster.module.circleBuild(detectionList, pageCharObject["elementList"], scale)

            return self.raster.module.execute(itemModuleList, ringList, lineObject, circleList, numberPage)

        def _pageCharCollect(self, password, pathInput):
            pageList = self.raster.module.pdfParse(pathInput, password)["pageList"]

            resultObject = {}

            for a in range(len(pageList)):
                resultObject[pageList[a]["number"]] = pageList[a]

            return resultObject

        def _pageStreamSplit(self, byteList):
            markerStart = b"\xff\xd8\xff"

            resultList = []

            position = byteList.find(markerStart)

            while position >= 0:
                positionNext = byteList.find(markerStart, position + len(markerStart))

                resultList.append(byteList[position:positionNext] if positionNext >= 0 else byteList[position:])

                position = positionNext

            return resultList

        def _boldFind(self, element):
            partList = element["fontPartList"] if "fontPartList" in element else [[element["fontName"], len(element["text"])]]

            count = 0
            countBold = 0

            for a in range(len(partList)):
                if partList[a][0] == "":
                    continue

                count += partList[a][1]

                if self.labelBold in partList[a][0].casefold():
                    countBold += partList[a][1]

            if count == 0:
                return None

            return countBold * 2 > count

        def _itemBuild(self, pageReader, image, countStart, numberPage):
            if pageReader is None or pageReader["width"] == 0 or pageReader["height"] == 0:
                return []

            imageHeight, imageWidth = image.shape[0:2]

            scaleX = imageWidth / pageReader["width"]
            scaleY = imageHeight / pageReader["height"]

            elementSplitObject = self._rotateSplit(self._widthCorrect(pageReader["elementList"], image, pageReader["rotate"], scaleX, scaleY))

            elementList = pdf.mergeText(self._bulletMark(elementSplitObject["elementList"]))

            resultList = []

            for a in range(len(elementList)):
                if elementList[a]["type"] != "text":
                    continue

                bboxList = [
                    int(round(elementList[a]["x0"] * scaleX)),
                    int(round(elementList[a]["y0"] * scaleY)),
                    int(round(elementList[a]["x1"] * scaleX)),
                    int(round(elementList[a]["y1"] * scaleY))
                ]

                resultList.append({
                    "id": countStart + len(resultList) + 1,
                    "page": numberPage,
                    "bbox": bboxList,
                    "centerPoint": centerPointCalculate(bboxList),
                    "text": elementList[a]["text"],
                    "fontSize": elementList[a]["fontSize"],
                    "isBold": self._boldFind(elementList[a])
                })

            resultList = self.raster.module.optionTextApply(resultList, pageReader["elementList"], scaleX) + self._rotateBuild(elementSplitObject["rotateList"], scaleX, scaleY, numberPage)

            for a in range(len(resultList)):
                resultList[a]["id"] = countStart + a + 1

            return resultList

        def _figureRelabel(self, astPage, pageReader, image):
            if pageReader is None or pageReader["width"] == 0 or pageReader["height"] == 0:
                return

            imageHeight, imageWidth = image.shape[0:2]

            scaleX = imageWidth / pageReader["width"]
            scaleY = imageHeight / pageReader["height"]

            elementList = pageReader["elementList"]

            itemList = astPage["itemList"]

            for a in range(len(itemList)):
                if itemList[a]["label"] not in self.raster.layout.labelFigureList:
                    continue

                bboxList = itemList[a]["bbox"]

                countText = 0

                isFigure = False

                for b in range(len(elementList)):
                    element = elementList[b]

                    x0 = element["x0"] * scaleX
                    y0 = element["y0"] * scaleY
                    x1 = element["x1"] * scaleX
                    y1 = element["y1"] * scaleY

                    if min(x1, bboxList[2]) <= max(x0, bboxList[0]) or min(y1, bboxList[3]) <= max(y0, bboxList[1]):
                        continue

                    if element["type"] == "text":
                        countText += 1

                        continue

                    if element["type"] == "image" or element["isCurve"]:
                        isFigure = True

                        break

                    size = min(element["x1"] - element["x0"], element["y1"] - element["y0"])

                    if element["isFill"] and size > self.levelFigureFill and self.raster.module._colorLightCheck(element["color"]) == False:
                        isFigure = True

                        break

                if isFigure == False and countText > 0:
                    itemList[a]["label"] = self.labelText

        def _rotateSplit(self, elementList):
            resultList = []
            rotateList = []

            for a in range(len(elementList)):
                if elementList[a]["type"] == "text" and elementList[a]["isVertical"] == False and elementList[a]["angle"] in self.angleRotateList:
                    rotateList.append(elementList[a])
                else:
                    resultList.append(elementList[a])

            return {"elementList": resultList, "rotateList": rotateList}

        def _rotateBuild(self, rotateList, scaleX, scaleY, numberPage):
            lineList = []

            for a in range(len(rotateList)):
                element = rotateList[a]

                lineObject = None

                for b in range(len(lineList)):
                    if lineList[b]["angle"] != element["angle"]:
                        continue

                    overlap = min(lineList[b]["x1"], element["x1"]) - max(lineList[b]["x0"], element["x0"])

                    if overlap >= min(lineList[b]["x1"] - lineList[b]["x0"], element["x1"] - element["x0"]) * self.levelBoxElementOverlap:
                        lineObject = lineList[b]

                        break

                if lineObject == None:
                    lineList.append({"angle": element["angle"], "x0": element["x0"], "y0": element["y0"], "x1": element["x1"], "y1": element["y1"], "elementList": [element]})

                    continue

                lineObject["x0"] = min(lineObject["x0"], element["x0"])
                lineObject["y0"] = min(lineObject["y0"], element["y0"])
                lineObject["x1"] = max(lineObject["x1"], element["x1"])
                lineObject["y1"] = max(lineObject["y1"], element["y1"])

                lineObject["elementList"].append(element)

            lineList.sort(key=lambda lineObject: (lineObject["angle"], lineObject["x0"] if lineObject["angle"] == 90 else -lineObject["x1"]))

            resultList = []

            for a in range(len(lineList)):
                lineObject = lineList[a]

                isUp = lineObject["angle"] == 90

                elementLineList = sorted(lineObject["elementList"], key=lambda elementObject: -elementObject["y1"] if isUp else elementObject["y0"])

                text = ""

                for b in range(len(elementLineList)):
                    textElement = elementLineList[b]["text"].strip()

                    if b > 0:
                        gap = elementLineList[b - 1]["y0"] - elementLineList[b]["y1"] if isUp else elementLineList[b]["y0"] - elementLineList[b - 1]["y1"]

                        if gap > elementLineList[b]["fontSize"] * levelSpaceGap:
                            text += " "

                    text += textElement

                size = lineObject["elementList"][0]["fontSize"]

                bboxList = [
                    int(round(lineObject["x0"] * scaleX)),
                    int(round(lineObject["y0"] * scaleY)),
                    int(round(lineObject["x1"] * scaleX)),
                    int(round(lineObject["y1"] * scaleY))
                ]

                itemPrevious = resultList[len(resultList) - 1] if len(resultList) > 0 else None

                if itemPrevious != None and itemPrevious["angle"] == lineObject["angle"] and max(lineObject["x0"] - itemPrevious["edge"], itemPrevious["edgeStart"] - lineObject["x1"]) <= size * self.levelRotateLine and min(itemPrevious["bbox"][3], bboxList[3]) > max(itemPrevious["bbox"][1], bboxList[1]):
                    itemPrevious["text"] = f"{itemPrevious['text']} {text}"
                    itemPrevious["bbox"] = [min(itemPrevious["bbox"][0], bboxList[0]), min(itemPrevious["bbox"][1], bboxList[1]), max(itemPrevious["bbox"][2], bboxList[2]), max(itemPrevious["bbox"][3], bboxList[3])]
                    itemPrevious["centerPoint"] = centerPointCalculate(itemPrevious["bbox"])
                    itemPrevious["edge"] = max(itemPrevious["edge"], lineObject["x1"])
                    itemPrevious["edgeStart"] = min(itemPrevious["edgeStart"], lineObject["x0"])

                    continue

                resultList.append({
                    "id": 0,
                    "page": numberPage,
                    "bbox": bboxList,
                    "centerPoint": centerPointCalculate(bboxList),
                    "text": text,
                    "fontSize": size,
                    "isBold": None,
                    "isRotate": True,
                    "angle": lineObject["angle"],
                    "edge": lineObject["x1"],
                    "edgeStart": lineObject["x0"]
                })

            for a in range(len(resultList)):
                del resultList[a]["angle"]
                del resultList[a]["edge"]
                del resultList[a]["edgeStart"]

            return resultList

        def _ruleSplit(self, elementList):
            horizontalList = []
            verticalList = []

            for a in range(len(elementList)):
                element = elementList[a]

                if element["type"] not in self.typeRuleList or element["isCurve"]:
                    continue

                width = element["x1"] - element["x0"]
                height = element["y1"] - element["y0"]

                if height <= self.levelRuleTouch and width > self.levelRuleTouch:
                    horizontalList.append(element)
                elif width <= self.levelRuleTouch and height > self.levelRuleTouch:
                    verticalList.append(element)
                elif element["type"] == "rect" and element["isStroke"] and width > self.levelRuleTouch and height > self.levelRuleTouch:
                    horizontalList.append({"x0": element["x0"], "y0": element["y0"], "x1": element["x1"], "y1": element["y0"]})
                    horizontalList.append({"x0": element["x0"], "y0": element["y1"], "x1": element["x1"], "y1": element["y1"]})
                    verticalList.append({"x0": element["x0"], "y0": element["y0"], "x1": element["x0"], "y1": element["y1"]})
                    verticalList.append({"x0": element["x1"], "y0": element["y0"], "x1": element["x1"], "y1": element["y1"]})

            horizontalList = sorted(horizontalList, key=lambda element: element["x0"])

            mergeList = []

            for a in range(len(horizontalList)):
                horizontal = horizontalList[a]

                centerY = (horizontal["y0"] + horizontal["y1"]) / 2

                index = -1

                for b in range(len(mergeList)):
                    if abs(mergeList[b]["y"] - centerY) <= self.levelRuleTouch and horizontal["x0"] <= mergeList[b]["x1"] + self.levelRuleTouch:
                        index = b

                if index < 0:
                    mergeList.append({"x0": horizontal["x0"], "x1": horizontal["x1"], "y": centerY})
                else:
                    mergeList[index]["x1"] = max(mergeList[index]["x1"], horizontal["x1"])

            return {"horizontalList": mergeList, "verticalList": verticalList}

        def _ruleHorizontalBuild(self, pageReader, image):
            imageHeight, imageWidth = image.shape[0:2]

            scaleX = imageWidth / pageReader["width"]
            scaleY = imageHeight / pageReader["height"]

            horizontalList = self._ruleSplit(pageReader["elementList"])["horizontalList"]

            resultList = []

            for a in range(len(horizontalList)):
                y = int(round(horizontalList[a]["y"] * scaleY))

                resultList.append([int(round(horizontalList[a]["x0"] * scaleX)), y, int(round(horizontalList[a]["x1"] * scaleX)), y])

            return resultList

        def _fieldRuleCollect(self, elementList, scaleX, scaleY):
            ruleObject = self._ruleSplit(elementList)

            horizontalList = ruleObject["horizontalList"]
            verticalList = ruleObject["verticalList"]

            resultList = []

            for a in range(len(horizontalList)):
                horizontal = horizontalList[a]

                top = horizontal["y"]

                positionList = []

                isStart = False
                isEnd = False

                for b in range(len(verticalList)):
                    vertical = verticalList[b]

                    if abs(vertical["y1"] - horizontal["y"]) > self.levelRuleTouch or vertical["x0"] < horizontal["x0"] - self.levelRuleTouch or vertical["x1"] > horizontal["x1"] + self.levelRuleTouch:
                        continue

                    positionList.append(vertical["x0"])

                    top = min(top, vertical["y0"])

                    if abs(vertical["x0"] - horizontal["x0"]) <= self.levelRuleTouch:
                        isStart = True

                    if abs(vertical["x1"] - horizontal["x1"]) <= self.levelRuleTouch:
                        isEnd = True

                if len(positionList) < self.countFieldRule or isStart == False or isEnd == False:
                    continue

                positionList = sorted(positionList)

                isCell = True

                for b in range(1, len(positionList)):
                    if positionList[b] - positionList[b - 1] > (horizontal["y"] - top) * self.levelFieldCell:
                        isCell = False

                if isCell:
                    resultList.append([horizontal["x0"] * scaleX, top * scaleY, horizontal["x1"] * scaleX, horizontal["y"] * scaleY])

            return resultList

        def _fieldLabelAboveFind(self, top, bboxList, skipList, itemList):
            result = None

            for a in range(len(itemList)):
                bboxItemList = itemList[a]["bbox"]

                height = bboxItemList[3] - bboxItemList[1]

                if itemList[a] in skipList or bboxItemList[3] > top + height * self.levelCaptionOverlap or top - bboxItemList[3] > height * self.levelCaptionGap:
                    continue

                if bboxItemList[0] < bboxList[0] - height or bboxItemList[0] > bboxList[2]:
                    continue

                if result == None or bboxItemList[3] > result["bbox"][3]:
                    result = itemList[a]

            return result

        def _lineParagraphCheck(self, itemObject, itemList):
            bboxList = itemObject["bbox"]

            height = bboxList[3] - bboxList[1]

            for a in range(len(itemList)):
                bboxOtherList = itemList[a]["bbox"]

                if itemList[a] is itemObject or itemList[a]["fontSize"] != itemObject["fontSize"] or bboxOtherList[0] >= bboxList[2] or bboxOtherList[2] <= bboxList[0]:
                    continue

                if (bboxOtherList[1] >= bboxList[3] and bboxOtherList[1] - bboxList[3] < height) or (bboxOtherList[3] <= bboxList[1] and bboxList[1] - bboxOtherList[3] < height):
                    return True

            return False

        def _fieldValueCollect(self, bboxList, itemList):
            resultList = []

            for a in range(len(itemList)):
                bboxItemList = itemList[a]["bbox"]

                centerX = (bboxItemList[0] + bboxItemList[2]) / 2
                centerY = (bboxItemList[1] + bboxItemList[3]) / 2

                if centerX > bboxList[0] and centerX < bboxList[2] and centerY > bboxList[1] and centerY < bboxList[3]:
                    resultList.append(itemList[a])

            for a in range(len(resultList)):
                if resultList[a]["bbox"][1] >= resultList[0]["bbox"][3] or resultList[a]["bbox"][3] <= resultList[0]["bbox"][1]:
                    return []

            return sorted(resultList, key=lambda itemObject: itemObject["bbox"][0])

        def _fieldAttach(self, image, pageReader, itemList, countStart):
            imageHeight, imageWidth = image.shape[0:2]

            fieldList = self._fieldRuleCollect(pageReader["elementList"], imageWidth / pageReader["width"], imageHeight / pageReader["height"])

            itemUprightList = []

            for a in range(len(itemList)):
                if "isRotate" not in itemList[a]:
                    itemUprightList.append(itemList[a])

            removeList = []

            for a in range(len(fieldList)):
                bboxList = fieldList[a]

                itemLabel = None

                captionList = []

                top = bboxList[1]

                for b in range(len(itemUprightList)):
                    bboxItemList = itemUprightList[b]["bbox"]

                    height = bboxItemList[3] - bboxItemList[1]

                    centerX = (bboxItemList[0] + bboxItemList[2]) / 2
                    centerY = (bboxItemList[1] + bboxItemList[3]) / 2

                    if itemUprightList[b] in removeList:
                        continue

                    if centerX > bboxList[0] and centerX < bboxList[2] and centerY < bboxList[1] and bboxItemList[3] > bboxList[1] - height:
                        captionList.append(itemUprightList[b])

                        top = min(top, bboxItemList[1])

                        continue

                    gap = bboxList[0] - bboxItemList[2]

                    if gap < 0 or bboxItemList[1] >= bboxList[3] or bboxItemList[3] + height <= bboxList[3] or self._lineParagraphCheck(itemUprightList[b], itemUprightList):
                        continue

                    if itemLabel == None or bboxItemList[2] > itemLabel["bbox"][2]:
                        itemLabel = itemUprightList[b]

                valueList = self._fieldValueCollect(bboxList, itemUprightList)

                if len(captionList) == 0 and len(valueList) == 0:
                    continue

                if itemLabel == None:
                    itemLabel = self._fieldLabelAboveFind(top, bboxList, captionList + valueList, itemUprightList)

                isCaption = itemLabel != None and len(captionList) > 0

                for b in range(len(captionList)):
                    if isCaption and captionList[b]["fontSize"] >= itemLabel["fontSize"]:
                        isCaption = False

                textValue = "".join(["".join(itemObject["text"].split()) for itemObject in valueList])

                if isCaption:
                    captionList = sorted(captionList, key=lambda itemObject: itemObject["bbox"][0])

                    itemLabel["text"] = f"{itemLabel['text']} ({' '.join([itemObject['text'] for itemObject in captionList])})"
                    itemLabel["isField"] = True

                    removeList = removeList + captionList

                if len(valueList) == 0:
                    continue

                if itemLabel == None:
                    valueList[0]["text"] = textValue
                    valueList[0]["bbox"][2] = valueList[len(valueList) - 1]["bbox"][2]
                    valueList[0]["centerPoint"] = centerPointCalculate(valueList[0]["bbox"])
                else:
                    itemLabel["text"] = f"{itemLabel['text']} {textValue}"
                    itemLabel["isField"] = True

                    removeList.append(valueList[0])

                removeList = removeList + valueList[1:]

            resultList = []

            for a in range(len(itemList)):
                if itemList[a] not in removeList:
                    itemList[a]["id"] = countStart + len(resultList) + 1

                    resultList.append(itemList[a])

            return resultList

        def _bulletMark(self, elementList):
            textList = []
            bulletList = []

            for a in range(len(elementList)):
                if elementList[a]["type"] == "text":
                    if elementList[a]["isVertical"] == False:
                        textList.append(elementList[a])

                    continue

                if elementList[a]["type"] == "path" and elementList[a]["isFill"]:
                    bulletList.append(elementList[a])

            matchList = []

            for a in range(len(bulletList)):
                textObject = self._bulletTextFind(bulletList[a], textList)

                if textObject != None:
                    matchList.append({"bullet": bulletList[a], "text": textObject})

            for a in range(len(matchList)):
                count = 0

                for b in range(len(matchList)):
                    if abs(matchList[a]["bullet"]["x0"] - matchList[b]["bullet"]["x0"]) <= matchList[a]["text"]["fontSize"] * self.levelBulletSize:
                        count += 1

                if count >= self.countBullet:
                    matchList[a]["text"]["text"] = f"{textBullet}{matchList[a]['text']['text']}"

            return elementList

        def _bulletTextFind(self, bulletObject, textList):
            centerY = (bulletObject["y0"] + bulletObject["y1"]) / 2

            width = bulletObject["x1"] - bulletObject["x0"]
            height = bulletObject["y1"] - bulletObject["y0"]

            result = None

            for a in range(len(textList)):
                if centerY < textList[a]["y0"] or centerY > textList[a]["y1"]:
                    continue

                size = textList[a]["fontSize"]

                if width > size * self.levelBulletSize or height > size * self.levelBulletSize:
                    continue

                if textList[a]["x0"] < bulletObject["x1"]:
                    return None

                if textList[a]["x0"] - bulletObject["x1"] > size * self.levelBulletGap:
                    continue

                if result == None or textList[a]["x0"] < result["x0"]:
                    result = textList[a]

            return result

        def _widthCorrect(self, elementList, image, rotate, scaleX, scaleY):
            isRotate = rotate == 90 or rotate == 270

            elementEstimatedList = []

            for a in range(len(elementList)):
                if elementList[a]["type"] != "text" or elementList[a]["isWidthEstimated"] == False:
                    continue

                elementEstimatedList.append({"element": elementList[a], "isVertical": elementList[a]["isVertical"] != isRotate})

            if len(elementEstimatedList) == 0:
                return elementList

            imageInk = imageInkBuild(image)

            boxList = self._boxDetectionCollect(image, imageInk)

            for a in range(len(boxList)):
                for b in range(len(self.axisList)):
                    isVertical = self.axisList[b]

                    nameFlow = "y" if isVertical else "x"
                    nameCross = "x" if isVertical else "y"

                    scaleFlow = scaleY if isVertical else scaleX
                    scaleCross = scaleX if isVertical else scaleY

                    groupList = self._groupCollect(elementEstimatedList, boxList[a], isVertical, nameFlow, nameCross, scaleFlow, scaleCross)

                    if len(groupList) == 0:
                        continue

                    flowStart = groupList[0][f"{nameFlow}0"]
                    flowEnd = groupList[len(groupList) - 1][f"{nameFlow}1"]

                    edge = self._inkEdge(imageInk, boxList[a], isVertical) / scaleFlow

                    if flowEnd <= flowStart or edge <= flowStart:
                        continue

                    ratio = (edge - flowStart) / (flowEnd - flowStart)

                    for c in range(len(groupList)):
                        groupList[c][f"{nameFlow}1"] = groupList[c][f"{nameFlow}0"] + (groupList[c][f"{nameFlow}1"] - groupList[c][f"{nameFlow}0"]) * ratio

            return elementList

        def _groupCollect(self, elementEstimatedList, boxObject, isVertical, nameFlow, nameCross, scaleFlow, scaleCross):
            resultList = []

            for a in range(len(elementEstimatedList)):
                if elementEstimatedList[a]["isVertical"] != isVertical:
                    continue

                element = elementEstimatedList[a]["element"]

                cross1 = max(element[f"{nameCross}0"] * scaleCross, boxObject[f"{nameCross}0"])
                cross2 = min(element[f"{nameCross}1"] * scaleCross, boxObject[f"{nameCross}1"])

                if cross2 - cross1 < (element[f"{nameCross}1"] - element[f"{nameCross}0"]) * scaleCross * self.levelBoxElementOverlap:
                    continue

                flowStart = element[f"{nameFlow}0"] * scaleFlow

                if flowStart < boxObject[f"{nameFlow}0"] or flowStart > boxObject[f"{nameFlow}1"]:
                    continue

                resultList.append(element)

            resultList.sort(key=lambda elementObject: elementObject[f"{nameFlow}0"])

            return resultList

        def _boxDetectionCollect(self, image, imageInk):
            detectionList = self.raster.ocr.boxDetect(image)

            resultList = []

            for a in range(len(detectionList)):
                bboxList = boxFromPointList(detectionList[a]["coordinate"])

                x0 = max(0, bboxList[0])
                y0 = max(0, bboxList[1])
                x1 = min(imageInk.shape[1], bboxList[2])
                y1 = min(imageInk.shape[0], bboxList[3])

                if x1 <= x0 or y1 <= y0:
                    continue

                resultList.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1})

            return resultList

        def _inkEdge(self, imageInk, boxObject, isVertical):
            region = imageInk[boxObject["y0"]:boxObject["y1"], boxObject["x0"]:boxObject["x1"]]

            valueList = region.sum(axis=1) if isVertical else region.sum(axis=0)

            start = boxObject["y0"] if isVertical else boxObject["x0"]

            for a in range(len(valueList) - 1, -1, -1):
                if valueList[a] > 0:
                    return start + a + 1

            return start

        def _debugWrite(self, itemList, image, pathOutput, numberPage):
            if self.raster.isDebug == False:
                return

            bboxList = []

            for a in range(len(itemList)):
                bboxList.append(itemList[a]["bbox"])

            boxDebugWrite(image, bboxList, f"{pathOutput}debug/ocr/{numberPage}.jpg")

        def _pageReaderCollect(self, pageReaderList, countPage):
            if len(pageReaderList) != countPage:
                print(f"raster.py - page count - raster {countPage}, text {len(pageReaderList)}")

            resultObject = {}

            for a in range(len(pageReaderList)):
                resultObject[pageReaderList[a]["number"]] = pageReaderList[a]

            return resultObject

        def execute(self, password, pathInput, pathOutput, job):
            pageList = self._pagePdfBuild(password, pathInput, pathOutput)

            if job["isCancel"]:
                return {"message": "Job cancelled."}

            pdfObject = pdf.Pdf(False).execute(pathInput, password)

            if pdfObject["message"] != "":
                return {"message": pdfObject["message"]}

            pageReaderObject = self._pageReaderCollect(pdfObject["pageList"], len(pageList))

            astPageList = []
            tableList = []
            itemList = []
            moduleList = []

            pageCharObject = None

            for a in range(len(pageList)):
                if job["isCancel"]:
                    return {"message": "Job cancelled."}

                pageObject = {"number": pageList[a]["number"], "image": cv2.imdecode(numpy.frombuffer(pageList[a]["byte"], dtype=numpy.uint8), cv2.IMREAD_COLOR)}

                astObject = self.raster.astBuild(pathOutput, pageObject)

                astPageList.append(astObject["astPage"])

                if job["isCancel"]:
                    return {"message": "Job cancelled."}

                numberPage = pageObject["number"]

                itemPageList = self._itemBuild(pageReaderObject[numberPage] if numberPage in pageReaderObject else None, pageObject["image"], len(itemList), numberPage)

                ruleList = []

                if len(itemPageList) == 0:
                    itemPageList = self.raster.itemOcrBuild(pageObject, pathOutput, astObject["tablePageList"], len(itemList), moduleList)

                    ruleList = self.raster.ruleImageBuild(pageObject["image"])
                else:
                    ruleList = self._ruleHorizontalBuild(pageReaderObject[numberPage], pageObject["image"])

                    self._figureRelabel(astObject["astPage"], pageReaderObject[numberPage], pageObject["image"])

                    self._debugWrite(itemPageList, pageObject["image"], pathOutput, numberPage)

                    bboxList = []

                    for b in range(len(itemPageList)):
                        bboxList.append(itemPageList[b]["bbox"])

                    if self.raster.moduleCheck(pageObject, astObject["tablePageList"], bboxList):
                        if pageCharObject == None:
                            pageCharObject = self._pageCharCollect(password, pathInput)

                        moduleList.append({"page": numberPage, "text": self._modulePdfBuild(pageObject, pageCharObject[numberPage])})
                    else:
                        itemPageList = self._fieldAttach(pageObject["image"], pageReaderObject[numberPage], itemPageList, len(itemList))

                if job["isCancel"]:
                    return {"message": "Job cancelled."}

                tableList = tableList + self.raster.pageAssemble(astObject["astPage"], itemPageList, ruleList, astObject["tablePageList"], pageObject, pathOutput, len(tableList))
                itemList = itemList + itemPageList

            return self.raster.documentBuild(astPageList, pathOutput, len(pageList), tableList, itemList, moduleList)

        def __init__(self, raster):
            self.resolution = "300"

            self.levelBoxElementOverlap = 0.5
            self.levelBulletSize = 0.6
            self.levelBulletGap = 3.0
            self.levelFigureFill = 3.0
            self.levelRotateLine = 1.5
            self.levelRuleTouch = 1.0
            self.levelCaptionGap = 2.0
            self.levelCaptionOverlap = 0.5
            self.levelFieldCell = 1.5

            self.countBullet = 2
            self.countFieldRule = 3

            self.labelBold = "bold"
            self.labelText = "text"

            self.axisList = [False, True]
            self.angleRotateList = [90, 270]
            self.typeRuleList = ["path", "rect"]

            self.raster = raster
