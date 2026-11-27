import sys
import cv2
import math
import difflib
import numpy

sys.dont_write_bytecode = True

# Source
import detection
import recognition
import vertical
import orientation
import watermark
from helper import sizeDominant, ideographLocaleDetect, wideTextCheck, imageInkBuild, boxFromPointList, boxCenterInsideCheck, boxIntersection, levelRuleLength, levelSpaceChar, levelSpaceGap, levelLineOverlap, levelLineDouble

class Raster:
    def _columnCheck(self, coordinateList):
        return math.dist(coordinateList[0], coordinateList[3]) >= math.dist(coordinateList[0], coordinateList[1]) * self.recognition.ratioRotate

    def _coordinateTurn(self, coordinateList):
        return [coordinateList[3], coordinateList[0], coordinateList[1], coordinateList[2]]

    def _scoreFind(self, image):
        detectionList = sorted(self.detection.execute(image), key=lambda detectionObject: max(math.dist(detectionObject["coordinate"][0], detectionObject["coordinate"][1]), math.dist(detectionObject["coordinate"][0], detectionObject["coordinate"][3])), reverse=True)[0:self.recognition.sizeBatch]

        coordinateList = [detectionObject["coordinate"] for detectionObject in detectionList if self._columnCheck(detectionObject["coordinate"]) == False]

        scoreList = [recognitionObject["score"] for recognitionObject in self.recognition.execute(coordinateList, image)]

        return sum(scoreList) / len(detectionList) if len(detectionList) > 0 else 0.0

    def _angleFind(self, image, angleList):
        result = 0

        scoreBest = self._scoreFind(image) if len(angleList) > 0 else 0.0

        for a in range(len(angleList)):
            score = self._scoreFind(cv2.rotate(image, self.rotateObject[angleList[a]]))

            if score > scoreBest:
                result = angleList[a]
                scoreBest = score

        return result

    def _uprightFind(self, image):
        angle = self.orientation.execute(image)

        return self._angleFind(image, self.angleColumnList if angle in self.angleColumnList else [angleItem for angleItem in [angle] if angleItem in self.rotateObject])

    def _uprightBuild(self, image, angle):
        return cv2.rotate(image, self.rotateObject[angle]) if angle in self.rotateObject else image

    def _skewFind(self, detectionList):
        angleList = []

        for a in range(len(detectionList)):
            coordinateList = detectionList[a]["coordinate"]

            width = math.dist(coordinateList[0], coordinateList[1])

            if width >= math.dist(coordinateList[0], coordinateList[3]) * levelLineDouble:
                angleList += [math.atan2(coordinateList[1][1] - coordinateList[0][1], coordinateList[1][0] - coordinateList[0][0])] * int(width)

        angleList.sort()

        return angleList[int(len(angleList) / 2)] if len(angleList) > 0 else 0.0

    def _sizeMedian(self, detectionList):
        sizeList = sorted(min(math.dist(detectionObject["coordinate"][0], detectionObject["coordinate"][1]), math.dist(detectionObject["coordinate"][0], detectionObject["coordinate"][3])) for detectionObject in detectionList)

        return sizeList[int(len(sizeList) / 2)]

    def _skewBuild(self, image, angle):
        imageHeight, imageWidth = image.shape[0:2]

        matrix = cv2.getRotationMatrix2D((imageWidth / 2, imageHeight / 2), math.degrees(angle), 1.0)

        width = int(imageHeight * abs(matrix[0][1]) + imageWidth * abs(matrix[0][0]))
        height = int(imageHeight * abs(matrix[0][0]) + imageWidth * abs(matrix[0][1]))

        matrix[0][2] += (width - imageWidth) / 2
        matrix[1][2] += (height - imageHeight) / 2

        return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    def _quadList(self, detectionList, image):
        watermarkObject = self.watermark.execute([boxFromPointList(detectionObject["coordinate"]) for detectionObject in detectionList], image)

        if watermarkObject["isFound"] == False:
            return [{"coordinate": detectionObject["coordinate"], "image": image, "isColumn": False, "isTurn": False} for detectionObject in detectionList]

        mergeObject = self.watermark.detectionMerge(detectionList, watermarkObject["zone"], self.detection.execute(watermarkObject["image"]), self.recognition, watermarkObject["image"])

        return [{"coordinate": detectionList[a]["coordinate"], "image": image, "isColumn": False, "isTurn": False} for a in range(len(detectionList)) if mergeObject["isKeepList"][a]] + [{"coordinate": detectionObject["coordinate"], "image": watermarkObject["image"], "isColumn": False, "isTurn": False} for detectionObject in mergeObject["detectionZoneList"]]

    def _turnCheck(self, quadList, image):
        quadLineList = sorted([quadObject for quadObject in quadList if quadObject["image"] is image and self._columnCheck(quadObject["coordinate"]) == False], key=lambda quadObject: math.dist(quadObject["coordinate"][0], quadObject["coordinate"][1]), reverse=True)[0:self.recognition.sizeBatch]

        coordinateList = []

        for a in range(len(quadLineList)):
            pointList = numpy.array(quadLineList[a]["coordinate"], dtype=numpy.float64)

            side = pointList[3] - pointList[0]

            length = math.dist(pointList[0], pointList[1])
            thickness = math.dist(pointList[0], pointList[3])

            step = (pointList[1] - pointList[0]) / length * thickness

            for b in range(int(length / thickness)):
                start = pointList[0] + step * b

                coordinateList.append([start, start + step, start + step + side, start + side])

        count = len(coordinateList)

        scoreList = [recognitionObject["score"] for recognitionObject in self.recognition.execute(coordinateList + [self._coordinateTurn(coordinate) for coordinate in coordinateList], image)]

        return len([a for a in range(count) if scoreList[count + a] > scoreList[a]]) * 2 > count

    def _textRecognize(self, quadList, image, isColumn):
        indexList = [a for a in range(len(quadList)) if quadList[a]["image"] is image and quadList[a]["isColumn"] == isColumn]

        reader = self.vertical if isColumn else self.recognition

        recognitionList = reader.execute([quadList[index]["coordinate"] for index in indexList], image) if len(indexList) > 0 else []

        for a in range(len(indexList)):
            quadList[indexList[a]]["text"] = recognitionList[a]["text"]
            quadList[indexList[a]]["score"] = recognitionList[a]["score"]
            quadList[indexList[a]]["positionList"] = recognitionList[a]["positionList"]

    def _turnResolve(self, quadList, image):
        indexList = [a for a in range(len(quadList)) if quadList[a]["image"] is image and self._columnCheck(self._coordinateTurn(quadList[a]["coordinate"])) == False]

        coordinateList = [self._coordinateTurn(quadList[index]["coordinate"]) for index in indexList]

        recognitionList = self.recognition.execute(coordinateList, image)

        for a in range(len(indexList)):
            if recognitionList[a]["score"] > quadList[indexList[a]]["score"]:
                quadList[indexList[a]]["coordinate"] = coordinateList[a]
                quadList[indexList[a]]["text"] = recognitionList[a]["text"]
                quadList[indexList[a]]["score"] = recognitionList[a]["score"]
                quadList[indexList[a]]["positionList"] = recognitionList[a]["positionList"]
                quadList[indexList[a]]["isTurn"] = True

    def _columnResolve(self, quadList, isTurn):
        isLocale = ideographLocaleDetect("".join(quadObject["text"] for quadObject in quadList)) == self.vertical.locale

        for a in range(len(quadList)):
            quadList[a]["isColumn"] = isLocale and len(quadList[a]["text"]) > 1 and wideTextCheck(quadList[a]["text"]) and quadList[a]["isTurn"] == False and self._columnCheck(quadList[a]["coordinate"]) != isTurn

    def _rubyResolve(self, quadList):
        boxList = [boxFromPointList(quadObject["coordinate"]) for quadObject in quadList]

        for a in range(len(quadList)):
            thickness = boxList[a][3] - boxList[a][1]

            for b in range(len(quadList)):
                overlap = min(boxList[a][2], boxList[b][2]) - max(boxList[a][0], boxList[b][0])

                isSide = boxList[a][1] + boxList[a][3] < boxList[b][1] + boxList[b][3] and boxList[a][3] - boxList[b][1] > thickness * levelSpaceGap

                if quadList[a]["isTurn"] == False and quadList[b]["isTurn"] == False and thickness <= (boxList[b][3] - boxList[b][1]) * self.levelRuby and overlap >= (boxList[a][2] - boxList[a][0]) * levelLineOverlap and isSide:
                    quadList[a]["text"] = ""
                    quadList[a]["positionList"] = []
                    quadList[a]["isColumn"] = False

    def _columnTrust(self, quadList):
        for a in range(len(quadList)):
            if quadList[a]["isColumn"] and quadList[a]["score"] < self.watermark.levelScore:
                quadList[a]["text"] = ""
                quadList[a]["positionList"] = []

    def _characterSpanList(self, wordList):
        resultList = []

        centerList = [(characterObject["start"] + characterObject["end"]) / 2 for characterObject in wordList]

        for a in range(len(wordList)):
            start = (centerList[a - 1] + centerList[a]) / 2 if a > 0 else wordList[a]["start"]
            end = (centerList[a] + centerList[a + 1]) / 2 if a < len(wordList) - 1 else wordList[a]["end"]

            resultList.append({"text": wordList[a]["text"], "start": min(1.0, start), "end": min(1.0, end)})

        return resultList

    def _boxBetweenCheck(self, boxList, start, end):
        return len([boxObject for boxObject in boxList if boxObject["bbox"][0] >= start and boxObject["bbox"][2] <= end]) > 0

    def _wordList(self, quadObject, scale, boxList):
        resultList = []

        bboxList = [value / scale for value in boxFromPointList(quadObject["coordinate"])]

        width = bboxList[2] - bboxList[0]
        height = bboxList[3] - bboxList[1]

        if quadObject["text"].strip() == "":
            return resultList

        if quadObject["isTurn"] or height >= width * self.recognition.ratioRotate:
            return [{"bbox": bboxList, "text": quadObject["text"].strip(), "size": width, "angle": self.angleTurn if quadObject["isTurn"] else 0, "isVertical": quadObject["isTurn"] == False and len(quadObject["text"].strip()) > 1, "fieldIndex": -1, "alternativeList": [[] for a in range(len(quadObject["text"].strip()))]}]

        boxLineList = [boxObject for boxObject in boxList if boxCenterInsideCheck(boxObject["bbox"], bboxList)]

        positionList = quadObject["positionList"] + [{"text": " ", "start": 1.0, "end": 1.0}]

        wordList = []
        phraseList = []

        for a in range(len(positionList)):
            isSplit = len(wordList) > 0 and (((positionList[a]["start"] + positionList[a]["end"]) / 2 - (wordList[len(wordList) - 1]["start"] + wordList[len(wordList) - 1]["end"]) / 2) * width >= height * (1 + levelSpaceChar) or self._boxBetweenCheck(boxLineList, bboxList[0] + width * wordList[len(wordList) - 1]["end"], bboxList[0] + width * positionList[a]["start"]))

            if positionList[a]["text"] != " " and isSplit == False:
                wordList.append(positionList[a])

                continue

            if len(wordList) == 0:
                continue

            wordObject = {"start": min(1.0, wordList[0]["start"]), "end": min(1.0, wordList[len(wordList) - 1]["end"]), "text": "".join(characterObject["text"] for characterObject in wordList), "alternativeList": [characterObject["alternativeList"] for characterObject in wordList], "positionList": self._characterSpanList(wordList)}

            if len(phraseList) > 0 and (wordObject["start"] - phraseList[len(phraseList) - 1]["end"]) * width < height * levelSpaceChar and self._boxBetweenCheck(boxLineList, bboxList[0] + width * phraseList[len(phraseList) - 1]["end"], bboxList[0] + width * wordObject["start"]) == False:
                phraseList[len(phraseList) - 1]["positionList"] += [{"text": " ", "start": phraseList[len(phraseList) - 1]["end"], "end": wordObject["start"]}] + wordObject["positionList"]
                phraseList[len(phraseList) - 1]["end"] = wordObject["end"]
                phraseList[len(phraseList) - 1]["text"] += f" {wordObject['text']}"
                phraseList[len(phraseList) - 1]["alternativeList"] += [[]] + wordObject["alternativeList"]
            else:
                phraseList.append(wordObject)

            wordList = [positionList[a]] if positionList[a]["text"] != " " else []

        for a in range(len(phraseList)):
            widthPhrase = phraseList[a]["end"] - phraseList[a]["start"]

            resultList.append({"bbox": [bboxList[0] + width * phraseList[a]["start"], bboxList[1], bboxList[0] + width * phraseList[a]["end"], bboxList[3]], "text": phraseList[a]["text"], "size": height, "angle": 0, "isVertical": False, "fieldIndex": -1, "alternativeList": phraseList[a]["alternativeList"], "positionList": [{"text": positionObject["text"], "start": (positionObject["start"] - phraseList[a]["start"]) / widthPhrase if widthPhrase > 0 else 0.0, "end": (positionObject["end"] - phraseList[a]["start"]) / widthPhrase if widthPhrase > 0 else 1.0} for positionObject in phraseList[a]["positionList"]]})

        return resultList

    def _borderSize(self, imageInk, x, y, stepX, stepY, limit):
        result = 0

        for a in range(limit):
            if x < 0 or y < 0 or x >= imageInk.shape[1] or y >= imageInk.shape[0] or imageInk[y][x] == 0:
                break

            result += 1

            x += stepX
            y += stepY

        return result

    def _voidList(self, imageInk, imageBorder):
        resultList = []

        contourList, hierarchyList = cv2.findContours(imageInk, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)

        for a in range(len(contourList)):
            x, y, width, height = cv2.boundingRect(contourList[a])

            index = hierarchyList[0][a][3]

            if index != -1 and cv2.contourArea(contourList[a]) >= (width - 1) * (height - 1) * (1 - levelSpaceGap):
                limit = min(width, height)

                left = self._borderSize(imageBorder, x - 1, y + int(height / 2), -1, 0, limit)
                right = self._borderSize(imageBorder, x + width, y + int(height / 2), 1, 0, limit)
                top = self._borderSize(imageBorder, x + int(width / 2), y - 1, 0, -1, limit)
                bottom = self._borderSize(imageBorder, x + int(width / 2), y + height, 0, 1, limit)

                xOuter, yOuter, widthOuter, heightOuter = cv2.boundingRect(contourList[index])

                resultList.append({"bbox": [x - left, y - top, x + width + right, y + height + bottom], "bboxOuter": [xOuter, yOuter, xOuter + widthOuter, yOuter + heightOuter], "center": [x + int(width / 2), y + int(height / 2)], "border": max(left, right, top, bottom)})

        return resultList

    def _characterPointList(self, quadList):
        resultList = []

        for a in range(len(quadList)):
            pointList = numpy.array(quadList[a]["coordinate"], dtype=numpy.float64)

            pointStart = (pointList[0] + pointList[3]) / 2
            pointEnd = (pointList[1] + pointList[2]) / 2

            if self._columnCheck(quadList[a]["coordinate"]):
                pointStart = (pointList[0] + pointList[1]) / 2
                pointEnd = (pointList[3] + pointList[2]) / 2

            for b in range(len(quadList[a]["positionList"])):
                positionObject = quadList[a]["positionList"][b]

                if positionObject["text"] != " ":
                    resultList.append(pointStart + (pointEnd - pointStart) * (positionObject["start"] + positionObject["end"]) / 2)

        return resultList

    def _shapeList(self, image, detectionList, scale, quadList):
        resultList = []
        boxList = []

        imageInk = imageInkBuild(image)

        imageBorder = imageInk.copy()

        length = max(3, int(round(self._sizeMedian(detectionList) * levelRuleLength)))

        for kernel in [numpy.ones((1, length), numpy.uint8), numpy.ones((length, 1), numpy.uint8)]:
            count, _, statList, _ = cv2.connectedComponentsWithStats(cv2.morphologyEx(imageInk, cv2.MORPH_OPEN, kernel))

            for a in range(1, count):
                x, y, width, height = statList[a][0:4]

                resultList.append({"bbox": [x / scale, y / scale, (x + width) / scale, (y + height) / scale], "isCurve": False})

        for a in range(len(detectionList)):
            cv2.fillPoly(imageInk, [numpy.array(detectionList[a]["coordinate"], dtype=numpy.int32)], 0)

        voidList = self._voidList(imageInk, imageBorder)

        pointList = self._characterPointList(quadList)

        centerList = [voidObject["center"] for voidObject in voidList]

        quadBoxList = [boxFromPointList(quadObject["coordinate"]) for quadObject in quadList]

        voidTextList = self._voidList(imageBorder, imageBorder)

        for a in range(len(voidTextList)):
            bboxList = voidTextList[a]["bbox"]

            if voidTextList[a]["center"] in centerList or max(abs(voidTextList[a]["bboxOuter"][b] - bboxList[b]) for b in range(4)) > voidTextList[a]["border"]:
                continue

            sizeLineList = [min(quadBox[2] - quadBox[0], quadBox[3] - quadBox[1]) for quadBox in quadBoxList if boxIntersection(quadBox, bboxList) > 0]

            if len(sizeLineList) == 0 or min(bboxList[2] - bboxList[0], bboxList[3] - bboxList[1]) < max(sizeLineList) * levelLineOverlap:
                continue

            if len([point for point in pointList if point[0] >= bboxList[0] and point[0] <= bboxList[2] and point[1] >= bboxList[1] and point[1] <= bboxList[3]]) == 0:
                boxList.append({"bbox": [value / scale for value in bboxList], "isCurve": False})

        for a in range(len(voidList)):
            resultList.append({"bbox": [value / scale for value in voidList[a]["bbox"]], "isCurve": False})

        return {"shapeList": resultList + boxList, "boxList": boxList}

    def zoneExecute(self, bboxList, scale, image):
        resultList = []

        left = max(0, int(bboxList[0] * scale))
        top = max(0, int(bboxList[1] * scale))

        imageZone = image[top:int(bboxList[3] * scale), left:int(bboxList[2] * scale)]

        quadList = [{"coordinate": detectionObject["coordinate"], "image": imageZone, "isColumn": False, "isTurn": False} for detectionObject in self.detection.execute(imageZone)]

        self._textRecognize(quadList, imageZone, False)

        for a in range(len(quadList)):
            wordList = self._wordList(quadList[a], scale, []) if quadList[a]["score"] >= self.watermark.levelScore else []

            for b in range(len(wordList)):
                bboxWordList = wordList[b]["bbox"]

                wordList[b]["bbox"] = [bboxWordList[0] + left / scale, bboxWordList[1] + top / scale, bboxWordList[2] + left / scale, bboxWordList[3] + top / scale]

            resultList += wordList

        return resultList

    def _textMerge(self, quadObject, recognitionObject):
        positionList = list(recognitionObject["positionList"])

        opcodeList = difflib.SequenceMatcher(None, quadObject["text"], recognitionObject["text"], autojunk=False).get_opcodes()

        for a in range(len(opcodeList)):
            if opcodeList[a][0] == "delete":
                positionList += [positionObject for positionObject in quadObject["positionList"][opcodeList[a][1]:opcodeList[a][2]] if positionObject["text"] != " "]

        positionList.sort(key=lambda positionObject: positionObject["start"] + positionObject["end"])

        quadObject["text"] = "".join(positionObject["text"] for positionObject in positionList)
        quadObject["score"] = recognitionObject["score"]
        quadObject["positionList"] = positionList

    def textExecute(self, imageLarge, rasterObject, scale):
        imageLarge = self._uprightBuild(imageLarge, rasterObject["angleUpright"])

        if rasterObject["isSkew"]:
            imageLarge = self._skewBuild(imageLarge, rasterObject["angleSkew"])

        ratio = imageLarge.shape[1] / rasterObject["widthText"]

        quadList = [quadObject for quadObject in rasterObject["quadList"] if quadObject["isPage"] and quadObject["isColumn"] == False]

        recognitionList = self.recognition.execute([[[point[0] * ratio, point[1] * ratio] for point in quadObject["coordinate"]] for quadObject in quadList], imageLarge)

        for a in range(len(quadList)):
            self._textMerge(quadList[a], recognitionList[a])

        pageObject = rasterObject["pageObject"]

        pageObject["textList"] = []

        for a in range(len(rasterObject["quadList"])):
            pageObject["textList"] += self._wordList(rasterObject["quadList"][a], scale * rasterObject["factor"], rasterObject["boxList"])

        pageObject["size"] = sizeDominant(pageObject["textList"]) if len(pageObject["textList"]) > 0 else 0

    def execute(self, image, scale):
        angleUpright = self._uprightFind(image)

        image = self._uprightBuild(image, angleUpright)

        detectionList = self.detection.execute(image)

        if len([detectionObject for detectionObject in detectionList if self._columnCheck(detectionObject["coordinate"])]) * 2 > len(detectionList):
            angleColumn = self._angleFind(image, self.angleColumnList)

            image = self._uprightBuild(image, angleColumn)

            angleUpright = (angleUpright + angleColumn) % 360

            detectionList = self.detection.execute(image) if angleColumn != 0 else detectionList

        pageObject = {"size": 0, "textList": [], "fieldList": [], "shapeList": [], "ruleList": []}

        if len(detectionList) == 0:
            return {"image": image, "pageObject": pageObject, "sizeLine": 0}

        angle = self._skewFind(detectionList)

        isSkew = abs(math.tan(angle)) * image.shape[1] > self._sizeMedian(detectionList) * levelLineOverlap

        if isSkew:
            image = self._skewBuild(image, angle)

            detectionList = self.detection.execute(image)

        sizeLine = self._sizeMedian(detectionList)

        factor = max(1.0, self.sizeText / sizeLine)

        imageText = image

        if factor > 1.0:
            imageText = cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)

            detectionList = self.detection.execute(imageText)

        quadList = self._quadList(detectionList, imageText)

        isTurn = angleUpright in self.angleColumnList and self._turnCheck(quadList, imageText)

        imageList = [imageText] + [quadObject["image"] for quadObject in quadList if quadObject["image"] is not imageText][0:1]

        for a in range(len(imageList)):
            self._textRecognize(quadList, imageList[a], False)

        if isTurn:
            self._turnResolve(quadList, imageText)

        self._columnResolve(quadList, isTurn)

        if isTurn:
            self._rubyResolve(quadList)

        for a in range(len(imageList)):
            self._textRecognize(quadList, imageList[a], True)

        self._columnTrust(quadList)

        for a in range(len(quadList)):
            quadList[a]["isPage"] = quadList[a]["image"] is imageText

        resultShapeObject = self._shapeList(imageText, detectionList, scale * factor, quadList)

        pageObject["shapeList"] = resultShapeObject["shapeList"]
        pageObject["ruleList"] = [shapeObject for shapeObject in pageObject["shapeList"] if min(shapeObject["bbox"][2] - shapeObject["bbox"][0], shapeObject["bbox"][3] - shapeObject["bbox"][1]) < max(shapeObject["bbox"][2] - shapeObject["bbox"][0], shapeObject["bbox"][3] - shapeObject["bbox"][1]) * levelSpaceGap]

        for a in range(len(quadList)):
            pageObject["textList"] += self._wordList(quadList[a], scale * factor, resultShapeObject["boxList"])

        pageObject["size"] = sizeDominant(pageObject["textList"]) if len(pageObject["textList"]) > 0 else 0

        return {"image": image, "pageObject": pageObject, "sizeLine": sizeLine, "angleUpright": angleUpright, "isSkew": isSkew, "angleSkew": angle, "factor": factor, "widthText": imageText.shape[1], "quadList": quadList, "boxList": resultShapeObject["boxList"], "isTurn": isTurn}

    def __init__(self):
        self.detection = detection.Detection()
        self.recognition = recognition.Recognition()
        self.vertical = vertical.Vertical()
        self.orientation = orientation.Orientation()
        self.watermark = watermark.Watermark()

        self.sizeText = self.recognition.imageHeightModel / 2

        self.rotateObject = {90: cv2.ROTATE_90_COUNTERCLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_CLOCKWISE}

        self.levelRuby = 0.6

        self.angleColumnList = [90, 270]
        self.angleTurn = 90
