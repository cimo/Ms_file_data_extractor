import sys
import os
import cv2
import icu
import numpy

sys.dont_write_bytecode = True

# Source
from helper import onnxSessionBuild, detrDetect, centerPointCalculate, boxArea, boxIntersection, boxIou, boxContainedRemove, rangeOverlapRatio, mediaImageWrite

class Layout:
    def _detect(self, image):
        detectionList = detrDetect(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), self.imageSizeLayout, cv2.INTER_CUBIC, self.onnxSessionLayout)

        resultList = []

        for a in range(len(detectionList)):
            classId = detectionList[a]["classId"]
            score = detectionList[a]["score"]

            label = self.labelObject[classId] if classId in self.labelObject else str(classId)

            if score < (self.scoreThresholdObject[label] if label in self.scoreThresholdObject else self.scoreThreshold):
                continue

            resultList.append({
                "label": label,
                "score": score,
                "bbox": detectionList[a]["bbox"],
                "centerPoint": centerPointCalculate(detectionList[a]["bbox"]),
                "path": "",
                "isAside": False,
                "columnX1": 0
            })

        return boxContainedRemove(self._boxSuppression(resultList), "bbox", self.levelBoxContained)

    def _boxSuppression(self, boxList):
        resultList = []

        boxSortedList = sorted(boxList, key=lambda boxObject: (boxObject["label"] in self.labelContainerList, boxObject["score"]), reverse=True)

        for a in range(len(boxSortedList)):
            area = boxArea(boxSortedList[a]["bbox"])

            isKeep = True

            for b in range(len(resultList)):
                areaIntersection = boxIntersection(boxSortedList[a]["bbox"], resultList[b]["bbox"])

                if areaIntersection == 0:
                    continue

                isSameRegion = boxIou(boxSortedList[a]["bbox"], resultList[b]["bbox"]) >= self.levelBoxNms
                isInside = areaIntersection / float(min(area, boxArea(resultList[b]["bbox"]))) >= self.levelBoxContained
                isSameGroup = self._labelGroupGet(boxSortedList[a]["label"]) == self._labelGroupGet(resultList[b]["label"])

                if isSameRegion or (isInside and isSameGroup):
                    isKeep = False

                    break

            if isKeep:
                resultList.append(boxSortedList[a])

        return resultList

    def _labelGroupGet(self, label):
        if label in self.labelGroupObject:
            return self.labelGroupObject[label]

        return label

    def _directionDetect(self, itemList):
        countRightToLeft = 0
        countLeftToRight = 0
        countVertical = 0
        countHorizontal = 0

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            if bboxList[3] - bboxList[1] >= (bboxList[2] - bboxList[0]) * self.levelVerticalRatio:
                countVertical += 1
            else:
                countHorizontal += 1

            text = itemList[a]["text"]

            for b in range(len(text)):
                direction = icu.Char.charDirection(text[b])

                if direction == icu.UCharDirection.RIGHT_TO_LEFT or direction == icu.UCharDirection.RIGHT_TO_LEFT_ARABIC:
                    countRightToLeft += 1
                elif direction == icu.UCharDirection.LEFT_TO_RIGHT:
                    countLeftToRight += 1

        return {"isVertical": countVertical > countHorizontal, "isRightToLeft": countRightToLeft > countLeftToRight}

    def _bboxProject(self, bboxList, imageWidth, directionObject):
        if directionObject["isVertical"]:
            return [bboxList[1], imageWidth - bboxList[2], bboxList[3], imageWidth - bboxList[0]]

        if directionObject["isRightToLeft"]:
            return [imageWidth - bboxList[2], bboxList[1], imageWidth - bboxList[0], bboxList[3]]

        return bboxList

    def _itemOrder(self, itemList, imageWidth, imageHeight):
        itemHeaderList = []
        itemFooterList = []
        itemBodyList = []

        for a in range(len(itemList)):
            if itemList[a]["label"] in self.labelHeaderList:
                itemHeaderList.append(itemList[a])
            elif itemList[a]["label"] in self.labelFooterList:
                itemFooterList.append(itemList[a])
            else:
                itemBodyList.append(itemList[a])

        resultList = sorted(itemHeaderList, key=lambda itemObject: itemObject["bboxOrder"][1])

        itemSortedList = sorted(itemBodyList, key=lambda itemObject: itemObject["bboxOrder"][1])

        itemBandList = []

        for a in range(len(itemSortedList)):
            bboxList = itemSortedList[a]["bboxOrder"]

            if (bboxList[2] - bboxList[0]) / float(imageWidth) < self.levelFullWidth:
                itemBandList.append(itemSortedList[a])

                continue

            resultList = resultList + self._bandOrder(itemBandList, imageHeight)
            resultList.append(itemSortedList[a])

            itemBandList = []

        resultList = resultList + self._bandOrder(itemBandList, imageHeight)

        return resultList + sorted(itemFooterList, key=lambda itemObject: itemObject["bboxOrder"][1])

    def _bandOrder(self, itemList, imageHeight):
        resultList = []

        columnList = self._columnGroup(itemList)

        y1Band = imageHeight
        y2Band = 0

        for a in range(len(itemList)):
            y1Band = min(y1Band, itemList[a]["bboxOrder"][1])
            y2Band = max(y2Band, itemList[a]["bboxOrder"][3])

        isBandTall = (y2Band - y1Band) / float(imageHeight) >= self.levelBandAside

        countFlowList = []
        countFlowMain = 0

        for a in range(len(columnList)):
            countFlowList.append(self._columnFlowCount(columnList[a]["itemList"]))

            if countFlowList[a] > countFlowMain:
                countFlowMain = countFlowList[a]

        for a in range(len(columnList)):
            isAside = isBandTall and countFlowMain > 0 and countFlowList[a] / float(countFlowMain) < self.levelColumnFlow

            itemColumnList = sorted(columnList[a]["itemList"], key=lambda itemObject: itemObject["bboxOrder"][1])

            for b in range(len(itemColumnList)):
                itemColumnList[b]["isAside"] = isAside
                itemColumnList[b]["columnX1"] = columnList[a]["x1"]

                resultList.append(itemColumnList[b])

        return resultList

    def _columnGroup(self, itemList):
        resultList = []

        itemSortedList = sorted(itemList, key=lambda itemObject: itemObject["bboxOrder"][0])

        for a in range(len(itemSortedList)):
            bboxList = itemSortedList[a]["bboxOrder"]

            isAdded = False

            for b in range(len(resultList)):
                if rangeOverlapRatio(bboxList[0], bboxList[2], resultList[b]["x1"], resultList[b]["x2"]) < self.levelColumnOverlap:
                    continue

                resultList[b]["x1"] = min(resultList[b]["x1"], bboxList[0])
                resultList[b]["x2"] = max(resultList[b]["x2"], bboxList[2])

                resultList[b]["itemList"].append(itemSortedList[a])

                isAdded = True

                break

            if isAdded == False:
                resultList.append({"x1": bboxList[0], "x2": bboxList[2], "itemList": [itemSortedList[a]]})

        return sorted(resultList, key=lambda columnObject: columnObject["x1"])

    def _columnFlowCount(self, itemList):
        result = 0

        for a in range(len(itemList)):
            if itemList[a]["label"] in self.labelFlowList:
                result += 1

        return result

    def _debugBox(self, image, itemList, pathOutput, numberPage):
        imageDebug = image.copy()

        labelDrawnList = []

        for a in range(len(itemList)):
            bboxList = itemList[a]["bbox"]

            color = self.labelColorObject[itemList[a]["label"]] if itemList[a]["label"] in self.labelColorObject else (0, 0, 0)

            boxRegion = imageDebug[bboxList[1]:bboxList[3], bboxList[0]:bboxList[2]]
            boxOverlay = numpy.full(boxRegion.shape, color, dtype=numpy.uint8)

            imageDebug[bboxList[1]:bboxList[3], bboxList[0]:bboxList[2]] = cv2.addWeighted(boxOverlay, self.levelDebugOpacity, boxRegion, 1 - self.levelDebugOpacity, 0)

            text = f"{itemList[a]['label']} {itemList[a]['score']:.2f}"

            textWidth, textHeight = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]

            x = bboxList[0]
            y = max(textHeight, bboxList[1] - 6)

            isOverlap = True

            while isOverlap:
                isOverlap = False

                for b in range(len(labelDrawnList)):
                    isSameRow = abs(y - labelDrawnList[b]["y"]) < textHeight + 4
                    isSameColumn = x < labelDrawnList[b]["x"] + labelDrawnList[b]["width"] and labelDrawnList[b]["x"] < x + textWidth

                    if isSameRow and isSameColumn:
                        isOverlap = True
                        y = labelDrawnList[b]["y"] - textHeight - 4

                        break

            labelDrawnList.append({"x": x, "y": y, "width": textWidth})

            cv2.putText(imageDebug, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        cv2.imwrite(f"{pathOutput}debug/layout/{numberPage}.jpg", imageDebug)

    def _documentColumn(self, astPageList):
        resultList = []

        for a in range(len(astPageList)):
            itemList = astPageList[a]["itemList"]

            tolerance = astPageList[a]["width"] * self.levelColumnTolerance

            for b in range(len(itemList)):
                countFlow = 1 if itemList[b]["label"] in self.labelFlowList else 0

                isAdded = False

                for c in range(len(resultList)):
                    if abs(resultList[c]["x1"] - itemList[b]["columnX1"]) > tolerance:
                        continue

                    resultList[c]["count"] += countFlow

                    if itemList[b]["isAside"]:
                        resultList[c]["isAside"] = True

                    isAdded = True

                    break

                if isAdded == False:
                    resultList.append({"x1": itemList[b]["columnX1"], "count": countFlow, "isAside": itemList[b]["isAside"]})

        return resultList

    def _columnFind(self, columnX1, columnList, tolerance):
        for a in range(len(columnList)):
            if abs(columnList[a]["x1"] - columnX1) <= tolerance:
                return columnList[a]

        return {"x1": columnX1, "count": 0, "isAside": False}

    def _itemFlow(self, itemObject, itemList, imageWidth, directionObject):
        if itemObject["isAside"]:
            return "secondary"

        if itemObject["label"] not in self.labelSecondaryList:
            return "main"

        if itemObject["label"] in self.labelFigureTitleList and self._figureNear(itemList, itemObject["bbox"], imageWidth, directionObject) == False:
            return "main"

        return "secondary"

    def _figureNear(self, itemList, bboxList, imageWidth, directionObject):
        bboxOrderList = self._bboxProject(bboxList, imageWidth, directionObject)

        for a in range(len(itemList)):
            if itemList[a]["label"] not in self.labelFigureList:
                continue

            bboxFigureList = self._bboxProject(itemList[a]["bbox"], imageWidth, directionObject)

            if min(bboxOrderList[2], bboxFigureList[2]) <= max(bboxOrderList[0], bboxFigureList[0]):
                continue

            heightTitle = bboxOrderList[3] - bboxOrderList[1]
            gapFigure = bboxOrderList[1] - bboxFigureList[3]

            if gapFigure < -heightTitle or gapFigure > heightTitle * self.levelFigureGap:
                continue

            return True

        return False

    def itemOrder(self, astPage, itemPageList):
        directionObject = self._directionDetect(itemPageList)

        itemList = astPage["itemList"]

        for a in range(len(itemList)):
            itemList[a]["bboxOrder"] = self._bboxProject(itemList[a]["bbox"], astPage["width"], directionObject)

        imageWidth = astPage["height"] if directionObject["isVertical"] else astPage["width"]
        imageHeight = astPage["width"] if directionObject["isVertical"] else astPage["height"]

        astPage["direction"] = directionObject
        astPage["itemList"] = self._itemOrder(itemList, imageWidth, imageHeight)

        for a in range(len(astPage["itemList"])):
            del astPage["itemList"][a]["bboxOrder"]

    def mediaWrite(self, astPage, image, pathOutput):
        itemList = astPage["itemList"]

        for a in range(len(itemList)):
            if itemList[a]["label"] not in self.labelFigureList:
                continue

            bboxList = itemList[a]["bbox"]

            imageCrop = image[bboxList[1]:bboxList[3], bboxList[0]:bboxList[2]]

            itemList[a]["path"] = mediaImageWrite(imageCrop, pathOutput)

    def flowAssign(self, astPageList):
        columnList = self._documentColumn(astPageList)

        countMain = 0

        for a in range(len(columnList)):
            if columnList[a]["count"] > countMain:
                countMain = columnList[a]["count"]

        for a in range(len(astPageList)):
            itemList = astPageList[a]["itemList"]

            tolerance = astPageList[a]["width"] * self.levelColumnTolerance

            itemMainList = []
            itemSecondaryList = []

            for b in range(len(itemList)):
                columnObject = self._columnFind(itemList[b]["columnX1"], columnList, tolerance)

                if columnObject["count"] >= countMain * self.levelColumnDocument:
                    itemList[b]["isAside"] = False
                elif columnObject["isAside"]:
                    itemList[b]["isAside"] = True

                if self._itemFlow(itemList[b], itemList, astPageList[a]["width"], astPageList[a]["direction"]) == "main":
                    itemMainList.append(itemList[b])
                else:
                    itemSecondaryList.append(itemList[b])

            astPageList[a]["itemMainList"] = itemMainList
            astPageList[a]["itemSecondaryList"] = itemSecondaryList

            del astPageList[a]["itemList"]

    def resultBuild(self, astPage, countStart):
        resultList = []

        flowObject = {"main": astPage["itemMainList"], "secondary": astPage["itemSecondaryList"]}

        for flow in flowObject:
            itemList = flowObject[flow]

            for a in range(len(itemList)):
                resultList.append({
                    "id": countStart + len(resultList) + 1,
                    "page": astPage["number"],
                    "flow": flow,
                    "label": itemList[a]["label"],
                    "score": itemList[a]["score"],
                    "bbox": itemList[a]["bbox"],
                    "centerPoint": itemList[a]["centerPoint"],
                    "path": itemList[a]["path"]
                })

        return resultList

    def directionBuild(self, astPageList):
        resultList = []

        for a in range(len(astPageList)):
            resultList.append({
                "page": astPageList[a]["number"],
                "isVertical": astPageList[a]["direction"]["isVertical"],
                "isRightToLeft": astPageList[a]["direction"]["isRightToLeft"]
            })

        return resultList

    def execute(self, pathOutput, image, numberPage):
        imageHeight, imageWidth = image.shape[0:2]

        itemList = self._detect(image)

        if self.isDebug:
            self._debugBox(image, itemList, pathOutput, numberPage)

        return {"number": numberPage, "width": imageWidth, "height": imageHeight, "itemList": itemList}

    def __init__(self, isDebug):
        self.isDebug = isDebug

        self.pathModelLayout = f"{os.path.dirname(__file__)}/model/pp-docLayout_plus-l.onnx"

        self.imageSizeLayout = 800

        self.levelBoxContained = 0.9
        self.levelBoxNms = 0.5
        self.levelBandAside = 0.5
        self.levelVerticalRatio = 2.0
        self.levelColumnDocument = 0.25
        self.levelColumnFlow = 0.5
        self.levelColumnTolerance = 0.02
        self.levelColumnOverlap = 0.5
        self.levelFigureGap = 2.0
        self.levelFullWidth = 0.7
        self.levelDebugOpacity = 0.2

        self.scoreThreshold = 0.3
        self.scoreThresholdObject = {"table": 0.35}

        self.labelObject = {
            12: "header",
            10: "doc_title",
            4: "abstract",
            5: "content",
            0: "paragraph_title",
            2: "text",
            1: "image",
            6: "figure_title",
            16: "chart",
            8: "table",
            7: "formula",
            17: "formula_number",
            13: "algorithm",
            18: "aside_text",
            9: "reference",
            19: "reference_content",
            11: "footnote",
            14: "footer",
            3: "number",
            15: "seal"
        }
        self.labelGroupObject = {
            "text": "text",
            "header": "text",
            "footer": "text",
            "footnote": "text",
            "aside_text": "text",
            "abstract": "text",
            "content": "text",
            "reference_content": "text",
            "paragraph_title": "text",
            "figure_title": "text"
        }
        self.labelColorObject = {
            "header": (128, 128, 128),
            "doc_title": (255, 0, 0),
            "abstract": (0, 200, 0),
            "content": (0, 200, 0),
            "paragraph_title": (255, 0, 0),
            "text": (0, 200, 0),
            "image": (0, 165, 255),
            "figure_title": (255, 0, 0),
            "chart": (0, 165, 255),
            "table": (0, 0, 255),
            "formula": (200, 0, 200),
            "formula_number": (200, 0, 200),
            "algorithm": (0, 200, 0),
            "aside_text": (128, 128, 128),
            "reference": (0, 200, 0),
            "reference_content": (0, 200, 0),
            "footnote": (128, 128, 128),
            "footer": (128, 128, 128),
            "number": (128, 128, 128),
            "seal": (128, 128, 128)
        }

        self.labelContainerList = ["table", "image", "chart"]
        self.labelFlowList = ["doc_title", "paragraph_title", "text", "abstract", "content", "reference", "reference_content"]
        self.labelFigureList = ["image", "chart"]
        self.labelFigureTitleList = ["figure_title"]
        self.labelHeaderList = ["header"]
        self.labelFooterList = ["footer"]
        self.labelSecondaryList = [
            "image",
            "number",
            "figure_title",
            "chart",
            "formula",
            "formula_number",
            "algorithm",
            "aside_text",
            "footnote",
            "seal"
        ]

        self.onnxSessionLayout = onnxSessionBuild(self.pathModelLayout)
