import sys
import subprocess
import cv2
import numpy

sys.dont_write_bytecode = True

# Source
import pdf
from helper import boxFromPointList, centerPointCalculate, imageInkBuild, boxDebugWrite, astWrite

class Raster:
    def astBuild(self, pathOutput, pageObject):
        astPage = self.layout.execute(pathOutput, pageObject["image"], pageObject["number"])

        return {"astPage": astPage, "tablePageList": self.table.execute(astPage, pageObject["image"])}

    def pageAssemble(self, astPage, itemPageList, tablePageList, pageObject, pathOutput, countTable):
        self.layout.itemOrder(astPage, itemPageList)

        self.table.orderAssign(astPage, tablePageList)

        self.layout.mediaWrite(astPage, pageObject["image"], pathOutput)

        self.table.cellRefine(tablePageList, itemPageList, astPage["direction"])

        self.table.textAssign(tablePageList, itemPageList, astPage["direction"])

        self.table.debugWrite(tablePageList, pageObject["image"], itemPageList, pathOutput, pageObject["number"], countTable)

        return self.table.resultBuild(tablePageList, countTable, pageObject["number"])

    def detectionBboxList(self, detectionList):
        resultList = []

        for a in range(len(detectionList)):
            resultList.append(boxFromPointList(detectionList[a]["coordinate"]))

        return resultList

    def formCheck(self, pageObject, tablePageList, bboxList):
        imageHeight, imageWidth = pageObject["image"].shape[0:2]

        return self.form.pageCheck(tablePageList, imageHeight * imageWidth, bboxList)

    def formBuild(self, detectionList, image, watermarkObject, numberPage, countStart, pathOutput):
        resultObject = self.form.itemImageBuild(detectionList, image, self.ocr.recognition, watermarkObject, numberPage)

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

        return {"itemList": itemList, "text": self.form.execute(resultObject["itemList"], resultObject["ringList"], resultObject["lineObject"], numberPage)}

    def watermarkApply(self, pageObject, pathOutput):
        detectionList = self.ocr.boxDetect(pageObject["image"])

        watermarkObject = self.watermark.execute(self.detectionBboxList(detectionList), pageObject["image"])

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
            return self.detectionBboxList(detectionList)

        resultList = []

        for a in range(len(detectionList)):
            if watermarkObject["isKeepList"][a]:
                resultList.append(boxFromPointList(detectionList[a]["coordinate"]))

        return resultList + self.detectionBboxList(watermarkObject["detectionZoneList"])

    def itemOcrBuild(self, pageObject, pathOutput, tablePageList, countStart, formList):
        ocrObject = self.watermarkApply(pageObject, pathOutput)

        if self.formCheck(pageObject, tablePageList, self.detectionCheckList(ocrObject["detectionList"], ocrObject["watermarkObject"])):
            formObject = self.formBuild(ocrObject["detectionList"], pageObject["image"], ocrObject["watermarkObject"], pageObject["number"], countStart, pathOutput)

            formList.append({"page": pageObject["number"], "text": formObject["text"]})

            return formObject["itemList"]

        return self.ocr.execute(ocrObject["detectionList"], pageObject["image"], tablePageList, ocrObject["watermarkObject"], countStart, pageObject["number"], pathOutput)

    def documentBuild(self, astPageList, pathOutput, countPage, tableList, itemList, formList):
        self.layout.flowAssign(astPageList)

        layoutList = []

        for a in range(len(astPageList)):
            layoutList = layoutList + self.layout.resultBuild(astPageList[a], len(layoutList))

        if self.isDebug:
            astWrite(pathOutput, astPageList)

        return {
            "pageCount": countPage,
            "directionList": self.layout.directionBuild(astPageList),
            "layoutList": layoutList,
            "tableList": tableList,
            "itemList": itemList,
            "formList": formList
        }

    def __init__(self, isDebug, layout, table, ocr, form, watermark):
        self.isDebug = isDebug

        self.layout = layout
        self.table = table
        self.ocr = ocr
        self.form = form
        self.watermark = watermark

        self.image = Raster.Image(self)
        self.pdf = Raster.Pdf(self)

    class Image:
        def _pageBuild(self, pathInput, pathOutput):
            image = cv2.imread(pathInput)

            if image is None:
                return []

            if self.raster.isDebug:
                cv2.imwrite(f"{pathOutput}debug/page/{self.numberPageFirst}.jpg", image)

            return [{"number": self.numberPageFirst, "image": image}]

        def execute(self, pathInput, pathOutput, job):
            pageList = self._pageBuild(pathInput, pathOutput)

            astPageList = []
            tableList = []
            itemList = []
            formList = []

            for a in range(len(pageList)):
                if job["isCancel"]:
                    return {"message": "Job cancelled."}

                astObject = self.raster.astBuild(pathOutput, pageList[a])

                astPageList.append(astObject["astPage"])

                if job["isCancel"]:
                    return {"message": "Job cancelled."}

                itemPageList = self.raster.itemOcrBuild(pageList[a], pathOutput, astObject["tablePageList"], len(itemList), formList)

                if job["isCancel"]:
                    return {"message": "Job cancelled."}

                tableList = tableList + self.raster.pageAssemble(astObject["astPage"], itemPageList, astObject["tablePageList"], pageList[a], pathOutput, len(tableList))
                itemList = itemList + itemPageList

            return self.raster.documentBuild(astPageList, pathOutput, len(pageList), tableList, itemList, formList)

        def __init__(self, raster):
            self.numberPageFirst = 1

            self.raster = raster

    class Pdf:
        def _pageBuild(self, password, pathInput, pathOutput):
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

        def _formPdfBuild(self, pageObject, pageCharObject):
            numberPage = pageObject["number"]

            scale = pageObject["image"].shape[1] / pageCharObject["width"]

            itemFormList = self.raster.form.itemPdfBuild(pageCharObject["elementList"], scale, numberPage)

            detectionList = self.raster.ocr.boxDetect(pageObject["image"])

            ringList = self.raster.form.ringBuild(pageObject["image"], detectionList)

            lineObject = self.raster.form.lineBuild(pageObject["image"], detectionList)

            return self.raster.form.execute(itemFormList, ringList, lineObject, numberPage)

        def _pageCharCollect(self, password, pathInput):
            pageList = self.raster.form.pdfParse(pathInput, password)["pageList"]

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

        def _itemBuild(self, pageReader, image, countStart, numberPage):
            if pageReader is None or pageReader["width"] == 0 or pageReader["height"] == 0:
                return []

            imageHeight, imageWidth = image.shape[0:2]

            scaleX = imageWidth / pageReader["width"]
            scaleY = imageHeight / pageReader["height"]

            elementList = pdf.mergeText(self._bulletMark(self._widthCorrect(pageReader["elementList"], image, pageReader["rotate"], scaleX, scaleY)))

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
                    "isBold": self.labelBold in elementList[a]["fontName"].casefold() if elementList[a]["fontName"] != "" else None
                })

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
                    matchList[a]["text"]["text"] = f"- {matchList[a]['text']['text']}"

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

            boxList = self._boxCollect(image, imageInk)

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

                if cross2 - cross1 < (element[f"{nameCross}1"] - element[f"{nameCross}0"]) * scaleCross * self.levelBoxOverlap:
                    continue

                flowStart = element[f"{nameFlow}0"] * scaleFlow

                if flowStart < boxObject[f"{nameFlow}0"] or flowStart > boxObject[f"{nameFlow}1"]:
                    continue

                resultList.append(element)

            resultList.sort(key=lambda elementObject: elementObject[f"{nameFlow}0"])

            return resultList

        def _boxCollect(self, image, imageInk):
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
            pageList = self._pageBuild(password, pathInput, pathOutput)

            if job["isCancel"]:
                return {"message": "Job cancelled."}

            pdfObject = pdf.Pdf().execute(pathInput, password)

            if pdfObject["message"] != "":
                return {"message": pdfObject["message"]}

            pageReaderObject = self._pageReaderCollect(pdfObject["pageList"], len(pageList))

            astPageList = []
            tableList = []
            itemList = []
            formList = []

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

                if len(itemPageList) == 0:
                    itemPageList = self.raster.itemOcrBuild(pageObject, pathOutput, astObject["tablePageList"], len(itemList), formList)
                else:
                    self._debugWrite(itemPageList, pageObject["image"], pathOutput, numberPage)

                    bboxList = []

                    for b in range(len(itemPageList)):
                        bboxList.append(itemPageList[b]["bbox"])

                    if self.raster.formCheck(pageObject, astObject["tablePageList"], bboxList):
                        if pageCharObject == None:
                            pageCharObject = self._pageCharCollect(password, pathInput)

                        formList.append({"page": numberPage, "text": self._formPdfBuild(pageObject, pageCharObject[numberPage])})

                if job["isCancel"]:
                    return {"message": "Job cancelled."}

                tableList = tableList + self.raster.pageAssemble(astObject["astPage"], itemPageList, astObject["tablePageList"], pageObject, pathOutput, len(tableList))
                itemList = itemList + itemPageList

            return self.raster.documentBuild(astPageList, pathOutput, len(pageList), tableList, itemList, formList)

        def __init__(self, raster):
            self.resolution = "300"

            self.levelBoxOverlap = 0.5
            self.levelBulletSize = 0.6
            self.levelBulletGap = 3.0

            self.countBullet = 2

            self.labelBold = "bold"

            self.axisList = [False, True]

            self.raster = raster
