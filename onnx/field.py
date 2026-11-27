import sys
import cv2
import numpy

sys.dont_write_bytecode = True

# Source
from helper import imageInkBuild, boxArea, boxCenterInsideCheck, boxDistance, boxIntersection, textOptionMark, textOptionEmpty, textBlank, levelSpaceGap, levelSpaceWord, levelLineOverlap, levelOptionSide, labelImage, labelOptionMark, labelOptionList

class Field:
    def _markBuild(self, bboxList, text, size):
        return {"bbox": list(bboxList), "text": text, "size": size, "angle": 0, "isVertical": False, "fieldIndex": None}

    def _boxList(self, shapeList):
        resultList = []

        for a in range(len(shapeList)):
            bboxList = shapeList[a]["bbox"]

            if shapeList[a]["isCurve"]:
                continue

            if len([bboxOtherList for bboxOtherList in resultList if max(abs(bboxOtherList[b] - bboxList[b]) for b in range(4)) <= (bboxList[2] - bboxList[0]) * levelSpaceGap]) == 0:
                resultList.append(bboxList)

        return resultList

    def _rowCheck(self, bboxList, bboxOtherList):
        return min(bboxOtherList[3], bboxList[3]) - max(bboxOtherList[1], bboxList[1]) >= min(bboxOtherList[3] - bboxOtherList[1], bboxList[3] - bboxList[1]) * levelLineOverlap

    def _insideCheck(self, bboxList, bboxOtherList):
        return self._rowCheck(bboxList, bboxOtherList) and bboxList[0] <= (bboxOtherList[0] + bboxOtherList[2]) / 2 <= bboxList[2]

    def _textInsideList(self, textList, bboxList):
        return [textObject for textObject in textList if self._insideCheck(bboxList, textObject["bbox"])]

    def _sideCheck(self, bboxList, bboxOtherList):
        width = bboxOtherList[2] - bboxOtherList[0]
        height = bboxOtherList[3] - bboxOtherList[1]

        if min(width, height) >= max(width, height) * levelSpaceGap:
            return False

        return max(width, height) >= (bboxList[2] - bboxList[0] if width > height else bboxList[3] - bboxList[1]) * (1 - levelSpaceGap)

    def _shapeInsideCheck(self, shapeList, bboxList):
        return len([shapeObject for shapeObject in shapeList if boxCenterInsideCheck(shapeObject["bbox"], bboxList) and boxArea(shapeObject["bbox"]) < boxArea(bboxList) * levelLineOverlap and self._sideCheck(bboxList, shapeObject["bbox"]) == False]) > 0

    def _labelFind(self, textList, bboxList):
        result = None

        distanceBest = 0

        for a in range(len(textList)):
            bboxTextList = textList[a]["bbox"]

            if self._rowCheck(bboxList, bboxTextList) == False or self._insideCheck(bboxList, bboxTextList):
                continue

            distance = max(bboxTextList[0] - bboxList[2], bboxList[0] - bboxTextList[2])

            if result == None or distance < distanceBest:
                result = textList[a]

                distanceBest = distance

        return result

    def _phraseStart(self, textList, textObject):
        result = textObject

        isFound = True

        while isFound:
            isFound = False

            for a in range(len(textList)):
                gap = result["bbox"][0] - textList[a]["bbox"][2]

                if textList[a] is not result and self._rowCheck(result["bbox"], textList[a]["bbox"]) and gap >= -result["size"] * levelSpaceGap and gap < result["size"] * levelSpaceWord:
                    result = textList[a]

                    isFound = True

                    break

        return result

    def _labelStack(self, textList, bboxList, textObject):
        sideShort = min(bboxList[2] - bboxList[0], bboxList[3] - bboxList[1])

        if max(textObject["bbox"][0] - bboxList[2], bboxList[0] - textObject["bbox"][2]) < sideShort:
            return None

        stackList = [textStackObject for textStackObject in textList if self._rowCheck(bboxList, textStackObject["bbox"]) == False and min(textStackObject["bbox"][2], bboxList[2]) > max(textStackObject["bbox"][0], bboxList[0]) and boxDistance(bboxList, textStackObject["bbox"]) < (textStackObject["bbox"][3] - textStackObject["bbox"][1]) * levelLineOverlap]

        if len(stackList) == 0:
            return None

        return self._phraseStart(textList, min(stackList, key=lambda textStackObject: boxDistance(bboxList, textStackObject["bbox"])))

    def _labelPartList(self, textObject, leftList):
        resultList = [None for a in range(len(leftList))]

        if "positionList" not in textObject or len(textObject["positionList"]) != len(textObject["text"]):
            resultList[0] = textObject

            return resultList

        width = textObject["bbox"][2] - textObject["bbox"][0]

        rangeList = [[] for a in range(len(leftList))]

        for a in range(len(textObject["text"])):
            if textObject["text"][a] == " ":
                continue

            if a == 0 or textObject["text"][a - 1] == " ":
                index = max([0] + [b for b in range(len(leftList)) if leftList[b] <= textObject["bbox"][0] + width * textObject["positionList"][a]["end"]])

            rangeList[index] = [rangeList[index][0] if len(rangeList[index]) > 0 else a, a + 1]

        for a in range(len(rangeList)):
            if len(rangeList[a]) == 0:
                continue

            start = textObject["positionList"][rangeList[a][0]]["start"]
            end = textObject["positionList"][rangeList[a][1] - 1]["end"]

            resultList[a] = dict(textObject)
            resultList[a]["bbox"] = [textObject["bbox"][0] + width * start, textObject["bbox"][1], textObject["bbox"][0] + width * end, textObject["bbox"][3]]
            resultList[a]["text"] = textObject["text"][rangeList[a][0]:rangeList[a][1]]
            resultList[a]["positionList"] = [{"text": positionObject["text"], "start": (positionObject["start"] - start) / (end - start) if end > start else 0.0, "end": (positionObject["end"] - start) / (end - start) if end > start else 1.0} for positionObject in textObject["positionList"][rangeList[a][0]:rangeList[a][1]]]

            if "alternativeList" in textObject:
                resultList[a]["alternativeList"] = textObject["alternativeList"][rangeList[a][0]:rangeList[a][1]]

        return resultList

    def _stackResolve(self, optionList, textList):
        resultList = list(textList)

        groupList = []

        for a in range(len(optionList)):
            if optionList[a]["labelStack"] == None:
                continue

            groupFoundList = [groupObject for groupObject in groupList if groupObject[0]["labelStack"] is optionList[a]["labelStack"]]

            if len(groupFoundList) == 0:
                groupList.append([optionList[a]])
            else:
                groupFoundList[0].append(optionList[a])

        for a in range(len(groupList)):
            if len(groupList[a]) < 2:
                continue

            textObject = groupList[a][0]["labelStack"]

            shareList = sorted(groupList[a], key=lambda optionObject: optionObject["bbox"][0])

            partList = self._labelPartList(textObject, [optionObject["bbox"][0] for optionObject in shareList])

            for b in range(len(shareList)):
                shareList[b]["labelStack"] = partList[b]

            resultList = [textOtherObject for textOtherObject in resultList if textOtherObject is not textObject] + [partObject for partObject in partList if partObject != None]

        return resultList

    def _markWrite(self, optionObject, text, resultList, textMarkList):
        if optionObject["labelStack"] == None:
            resultList.append(self._markBuild(optionObject["bbox"], text, optionObject["size"]))
        else:
            textObject = dict(optionObject["labelStack"])
            textObject["text"] = f"{text} {textObject['text'].strip()}"

            resultList.append(textObject)

            textMarkList.append(optionObject["labelStack"])

    def _inkSize(self, textObject, scale, imageInk):
        bboxList = textObject["bbox"]

        rowList = numpy.flatnonzero(imageInk[max(0, int(bboxList[1] * scale)):int(bboxList[3] * scale), max(0, int(bboxList[0] * scale)):int(bboxList[2] * scale)].sum(axis=1))

        if len(rowList) == 0:
            return textObject["size"]

        return min(textObject["size"], (rowList[len(rowList) - 1] - rowList[0] + 1) / scale)

    def _sizeCheck(self, bboxList, labelZone, sizeText, textObject):
        side = max(bboxList[2] - bboxList[0], bboxList[3] - bboxList[1])
        sideShort = min(bboxList[2] - bboxList[0], bboxList[3] - bboxList[1])

        if labelZone != "":
            return side - sideShort <= side * levelSpaceGap

        if sideShort < sizeText:
            return False

        return side < textObject["size"] * levelOptionSide and (side - sideShort <= side * levelSpaceGap or max(textObject["bbox"][0] - bboxList[2], bboxList[0] - textObject["bbox"][2]) < sideShort)

    def _zoneFind(self, zoneList, bboxList):
        for a in range(len(zoneList)):
            if zoneList[a]["label"] in labelOptionList and boxCenterInsideCheck(bboxList, zoneList[a]["bbox"]):
                return zoneList[a]["label"]

        return ""

    def _sameCheck(self, bboxList, bboxOtherList):
        return abs((bboxOtherList[2] - bboxOtherList[0]) - (bboxList[2] - bboxList[0])) <= (bboxList[2] - bboxList[0]) * levelSpaceGap and abs((bboxOtherList[3] - bboxOtherList[1]) - (bboxList[3] - bboxList[1])) <= (bboxList[3] - bboxList[1]) * levelSpaceGap

    def _combCheck(self, optionObject, optionList, isEmptyOnly):
        bboxList = optionObject["bbox"]

        for a in range(len(optionList)):
            bboxOtherList = optionList[a]["bbox"]

            if optionList[a] is optionObject or (optionList[a]["isEmpty"] == False and isEmptyOnly) or self._sameCheck(bboxList, bboxOtherList) == False:
                continue

            if self._rowCheck(bboxList, bboxOtherList) and max(bboxOtherList[0] - bboxList[2], bboxList[0] - bboxOtherList[2]) < max(bboxList[2] - bboxList[0], bboxList[3] - bboxList[1]):
                return True

        return False

    def _outlineCheck(self, bboxList, scale, imageGray):
        border = max(1, int(round(min(bboxList[2] - bboxList[0], bboxList[3] - bboxList[1]) * scale * levelSpaceGap)))

        left = int(round(bboxList[0] * scale)) - border * 2
        top = int(round(bboxList[1] * scale)) - border * 2
        right = int(round(bboxList[2] * scale)) + border * 2
        bottom = int(round(bboxList[3] * scale)) + border * 2

        if left < 0 or top < 0 or right > imageGray.shape[1] or bottom > imageGray.shape[0] or right - left <= border * 6 or bottom - top <= border * 6:
            return False

        imageOuter = imageGray[top:bottom, left:right].astype(numpy.float64)
        imageEdge = imageOuter[border:imageOuter.shape[0] - border, border:imageOuter.shape[1] - border]
        imageInner = imageOuter[border * 3:imageOuter.shape[0] - border * 3, border * 3:imageOuter.shape[1] - border * 3]

        levelOuter = (imageOuter.sum() - imageEdge.sum()) / (imageOuter.size - imageEdge.size)
        levelEdge = (imageEdge.sum() - imageInner.sum()) / (imageEdge.size - imageInner.size)

        levelInner = numpy.median(imageInner)

        return levelInner > levelEdge and levelInner >= levelOuter

    def _optionList(self, pageObject, zoneList, image, scale):
        resultList = []
        textMarkList = []

        optionList = []
        optionAllList = []

        boxList = self._boxList(pageObject["shapeList"])

        imageInk = imageInkBuild(image)

        for a in range(len(boxList)):
            textInsideList = self._textInsideList(pageObject["textList"], boxList[a])

            isShapeInside = self._shapeInsideCheck(pageObject["shapeList"], boxList[a])

            optionAllList.append({"bbox": boxList[a], "textInsideList": textInsideList, "isShapeInside": isShapeInside, "isEmpty": len(textInsideList) == 0 and isShapeInside == False})

            if len(textInsideList) == 0 and isShapeInside == False:
                imageInk[max(0, int(boxList[a][1] * scale)):int(boxList[a][3] * scale) + 1, max(0, int(boxList[a][0] * scale)):int(boxList[a][2] * scale) + 1] = 0

        for a in range(len(optionAllList)):
            optionObject = optionAllList[a]

            textObject = self._labelFind(pageObject["textList"], optionObject["bbox"])

            optionObject["labelZone"] = self._zoneFind(zoneList, optionObject["bbox"])

            sizeText = 0

            if textObject != None:
                sizeText = textObject["size"] if "font" in textObject else self._inkSize(textObject, scale, imageInk)

            if textObject == None or self._sizeCheck(optionObject["bbox"], optionObject["labelZone"], sizeText, textObject) == False or len([fieldObject for fieldObject in pageObject["fieldList"] if boxIntersection(fieldObject["bbox"], optionObject["bbox"]) > 0]) > 0:
                continue

            if len([zoneObject for zoneObject in zoneList if zoneObject["label"] == labelImage and boxCenterInsideCheck(optionObject["bbox"], zoneObject["bbox"])]) > 0:
                continue

            optionObject["size"] = textObject["size"]
            optionObject["labelStack"] = self._labelStack(pageObject["textList"], optionObject["bbox"], textObject)

            optionList.append(optionObject)

        textList = self._stackResolve(optionList, pageObject["textList"])

        imageGray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        for a in range(len(optionList)):
            optionObject = optionList[a]

            if optionObject["isEmpty"] and self._combCheck(optionObject, optionAllList, True) == False and self._outlineCheck(optionObject["bbox"], scale, imageGray):
                self._markWrite(optionObject, textOptionEmpty, resultList, textMarkList)
            elif optionObject["isEmpty"] == False and optionObject["labelZone"] == labelOptionMark:
                self._markWrite(optionObject, textOptionMark, resultList, textMarkList)

                textMarkList += optionObject["textInsideList"]
            elif len(optionObject["textInsideList"]) > 0 and optionObject["isShapeInside"] == False and self._combCheck(optionObject, optionAllList, False) == False and len([textObject for textObject in optionObject["textInsideList"] if textObject["bbox"][0] < optionObject["bbox"][0] or textObject["bbox"][2] > optionObject["bbox"][2]]) == 0 and self._outlineCheck(optionObject["bbox"], scale, imageGray):
                self._markWrite(optionObject, textOptionEmpty.replace(" ", " ".join(textObject["text"].strip() for textObject in optionObject["textInsideList"])), resultList, textMarkList)

                textMarkList += optionObject["textInsideList"]

        return [textObject for textObject in textList if len([textMarkObject for textMarkObject in textMarkList if textMarkObject is textObject]) == 0] + resultList

    def execute(self, pageObject, zoneList, image, scale):
        resultList = []

        for a in range(len(pageObject["fieldList"])):
            fieldObject = pageObject["fieldList"][a]

            if fieldObject["kind"] in self.fieldOptionList:
                resultList.append(self._markBuild(fieldObject["bbox"], textOptionEmpty if fieldObject["state"] in self.stateEmptyList else textOptionMark, pageObject["size"]))
            elif fieldObject["kind"] != self.fieldButton and fieldObject["label"] == "" and fieldObject["value"] == "" and len([textObject for textObject in pageObject["textList"] if textObject["fieldIndex"] == fieldObject["fieldIndex"]]) == 0:
                resultList.append(self._markBuild(fieldObject["bbox"], textBlank, pageObject["size"]))

        return self._optionList(pageObject, zoneList, image, scale) + resultList

    def __init__(self):
        self.fieldOptionList = ["check", "radio"]
        self.fieldButton = "button"

        self.stateEmptyList = ["", "Off"]
