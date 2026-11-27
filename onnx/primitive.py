import sys

sys.dont_write_bytecode = True

# Source
import pdf
from helper import boxCenterInsideCheck, sizeDominant, levelSpaceGap, levelLineOverlap, levelLineDouble

class Primitive:
    def _textBuild(self, element):
        return {
            "bbox": [element["x0"], element["y0"], element["x1"], element["y1"]],
            "text": element["text"],
            "size": element["fontSize"],
            "angle": element["angle"],
            "isVertical": element["isVertical"],
            "fieldIndex": element.get("fieldIndex"),
            "positionList": element["positionList"],
            "font": element["fontName"]
        }

    def _fieldBuild(self, element):
        return {
            "bbox": [element["x0"], element["y0"], element["x1"], element["y1"]],
            "kind": element["kind"],
            "label": element["label"],
            "value": element["value"],
            "state": element["state"],
            "fieldIndex": element["fieldIndex"]
        }

    def _shapeBuild(self, element):
        return {
            "bbox": [element["x0"], element["y0"], element["x1"], element["y1"]],
            "isCurve": element["isCurve"]
        }

    def _columnInsideCheck(self, bboxList, columnObject):
        bboxColumnList = columnObject["bbox"]

        width = bboxList[2] - bboxList[0]

        isAlign = min(bboxList[2], bboxColumnList[2]) - max(bboxList[0], bboxColumnList[0]) >= width * levelLineOverlap and width <= (bboxColumnList[2] - bboxColumnList[0]) * levelLineDouble

        return isAlign and max(bboxColumnList[1] - bboxList[3], bboxList[1] - bboxColumnList[3]) < columnObject["size"] * levelLineDouble

    def _pageTurn(self, pageObject, width):
        textList = pageObject["textList"]

        pageObject["isTurn"] = sum(len(textObject["text"]) for textObject in textList if textObject["isVertical"]) * 2 > sum(len(textObject["text"]) for textObject in textList)

        if pageObject["isTurn"] == False:
            return

        columnList = [textObject for textObject in textList if textObject["isVertical"]]

        insideList = [textObject for textObject in textList if textObject["isVertical"] == False and textObject["angle"] == 0 and len([columnObject for columnObject in columnList if self._columnInsideCheck(textObject["bbox"], columnObject)]) > 0]

        itemList = textList + pageObject["fieldList"] + pageObject["shapeList"] + [ruleObject for ruleObject in pageObject["ruleList"] if len([shapeObject for shapeObject in pageObject["shapeList"] if shapeObject is ruleObject]) == 0]

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            itemList[a]["bbox"] = [bboxList[1], width - bboxList[2], bboxList[3], width - bboxList[0]]

        for a in range(len(textList)):
            textList[a]["angle"] = 0 if textList[a]["isVertical"] or len([textObject for textObject in insideList if textObject is textList[a]]) > 0 else (textList[a]["angle"] + self.angleTurn) % 360
            textList[a]["isVertical"] = False

    def _pagePdf(self, pageReader):
        pageObject = {"size": 0, "textList": [], "fieldList": [], "shapeList": [], "ruleList": []}

        elementList = pageReader["elementList"]

        bboxPageList = [0, 0, pageReader["width"], pageReader["height"]]

        for a in range(len(elementList)):
            if elementList[a]["type"] == "text" and elementList[a]["text"].strip() != "":
                textObject = self._textBuild(elementList[a])

                if boxCenterInsideCheck(textObject["bbox"], bboxPageList):
                    pageObject["textList"].append(textObject)
            elif elementList[a]["type"] == "field":
                pageObject["fieldList"].append(self._fieldBuild(elementList[a]))
            elif elementList[a]["type"] in self.typeShapeList:
                shapeObject = self._shapeBuild(elementList[a])

                width = shapeObject["bbox"][2] - shapeObject["bbox"][0]
                height = shapeObject["bbox"][3] - shapeObject["bbox"][1]

                if width > 0 and height > 0:
                    pageObject["shapeList"].append(shapeObject)

                if shapeObject["isCurve"] == False and min(width, height) < max(width, height) * levelSpaceGap:
                    pageObject["ruleList"].append(shapeObject)

        pageObject["size"] = sizeDominant(pageObject["textList"])

        self._pageTurn(pageObject, pageReader["width"])

        return pageObject

    def pdfExecute(self, pathInput, password):
        readerObject = pdf.Pdf(False).execute(pathInput, password)

        if readerObject["message"] != "":
            return {"message": readerObject["message"], "pageList": []}

        pageList = []

        for a in range(len(readerObject["pageList"])):
            pageList.append(self._pagePdf(readerObject["pageList"][a]))

        return {"message": "", "pageList": pageList}

    def __init__(self):
        self.typeShapeList = ["rect", "path"]

        self.angleTurn = 90
