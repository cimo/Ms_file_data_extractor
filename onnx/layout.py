import sys
import os
import cv2
import numpy

sys.dont_write_bytecode = True

# Source
from helper import onnxSessionBuild, detrDetect, boxCenterInsideCheck, boxIntersection, labelTable, labelForm, labelFormula, labelFormulaInline, labelText

class Layout:
    def _zoneList(self, image, scale):
        imageHeight, imageWidth = image.shape[0:2]

        tensor = numpy.expand_dims((cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), (self.imageSize, self.imageSize), interpolation=cv2.INTER_LINEAR).astype(numpy.float32) / 255.0).transpose((2, 0, 1)), axis=0)

        tensorOutputList = self.onnxSession.run(None, {"pixel_values": tensor})

        scoreList = 1.0 / (1.0 + numpy.exp(-tensorOutputList[0][0].astype(numpy.float64)))

        resultList = []

        for a in range(scoreList.shape[0]):
            for b in range(scoreList.shape[1]):
                if scoreList[a][b] < self.scoreThreshold or self.labelList[b] == "":
                    continue

                centerX, centerY, width, height = tensorOutputList[1][0][a]

                resultList.append({"label": self.labelList[b], "score": float(scoreList[a][b]), "bbox": [max(0.0, float(centerX - width / 2)) * imageWidth / scale, max(0.0, float(centerY - height / 2)) * imageHeight / scale, min(1.0, float(centerX + width / 2)) * imageWidth / scale, min(1.0, float(centerY + height / 2)) * imageHeight / scale]})

        return resultList

    def _otherList(self, image, scale):
        resultList = []

        detectionList = detrDetect(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), self.imageSizeTable, cv2.INTER_CUBIC, self.onnxSessionTable)

        for a in range(len(detectionList)):
            if detectionList[a]["classId"] not in self.labelOtherObject or detectionList[a]["score"] < self.scoreThreshold:
                continue

            resultList.append({"label": self.labelOtherObject[detectionList[a]["classId"]], "score": detectionList[a]["score"], "bbox": [value / scale for value in detectionList[a]["bbox"]]})

        resultList.sort(key=lambda zoneObject: zoneObject["score"], reverse=True)

        return resultList

    def _formulaResolve(self, otherList, zoneList):
        formulaOtherList = [zoneObject for zoneObject in otherList if zoneObject["label"] == labelFormula]
        numberOtherList = [zoneObject for zoneObject in otherList if zoneObject["label"] == self.labelNumber]

        for a in range(len(zoneList)):
            if zoneList[a]["label"] != labelFormula:
                continue

            if len([zoneObject for zoneObject in formulaOtherList if boxCenterInsideCheck(zoneObject["bbox"], zoneList[a]["bbox"]) or boxCenterInsideCheck(zoneList[a]["bbox"], zoneObject["bbox"])]) == 0:
                zoneList[a]["label"] = labelText

                continue

            zoneList[a]["numberList"] = [zoneObject["bbox"] for zoneObject in numberOtherList if boxCenterInsideCheck(zoneObject["bbox"], zoneList[a]["bbox"])]

        formulaList = [zoneObject for zoneObject in zoneList if zoneObject["label"] == labelFormula]
        inlineList = []

        for a in range(len(formulaOtherList)):
            bboxList = formulaOtherList[a]["bbox"]

            if len([zoneObject for zoneObject in formulaList if boxCenterInsideCheck(bboxList, zoneObject["bbox"]) or boxCenterInsideCheck(zoneObject["bbox"], bboxList)]) > 0:
                continue

            if len([zoneObject for zoneObject in inlineList if boxIntersection(bboxList, zoneObject["bbox"]) > 0]) > 0:
                continue

            inlineList.append({"label": labelFormulaInline, "score": formulaOtherList[a]["score"], "bbox": bboxList})

        zoneList += inlineList

    def execute(self, image, scale):
        zoneList = self._zoneList(image, scale)

        formList = [zoneObject for zoneObject in zoneList if zoneObject["label"] == labelForm]
        tableList = [zoneObject for zoneObject in zoneList if zoneObject["label"] == labelTable]

        otherList = self._otherList(image, scale)

        self._formulaResolve(otherList, zoneList)

        tableOtherList = [zoneObject for zoneObject in otherList if zoneObject["label"] == labelTable]

        for a in range(len(tableOtherList)):
            bboxList = tableOtherList[a]["bbox"]

            if len([formObject for formObject in formList if boxCenterInsideCheck(bboxList, formObject["bbox"])]) > 0:
                continue

            if len([tableObject for tableObject in tableList if boxIntersection(bboxList, tableObject["bbox"]) > 0]) > 0:
                continue

            tableList.append(tableOtherList[a])
            zoneList.append(tableOtherList[a])

        return zoneList

    def __init__(self):
        pathModel = f"{os.path.dirname(os.path.abspath(__file__))}/model"

        self.imageSize = 640
        self.imageSizeTable = 800

        self.scoreThreshold = 0.5

        self.labelNumber = "formula_number"
        self.labelOtherObject = {7: labelFormula, 8: labelTable, 17: self.labelNumber}

        self.labelList = ["caption", "footnote", "formula", "list_item", "footer", "header", "image", "paragraph_title", "table", "text", "doc_title", "document_index", "code", "checkbox_selected", "checkbox_unselected", "form", ""]

        self.onnxSession = onnxSessionBuild(f"{pathModel}/docling/Docling-Layout-Heron/docling-layout-heron.onnx")
        self.onnxSessionTable = onnxSessionBuild(f"{pathModel}/paddle/PP-DocLayout_plus-L/pp-docLayout_plus-l.onnx")
