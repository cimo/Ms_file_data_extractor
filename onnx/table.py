import sys
import os
import cv2
import numpy

sys.dont_write_bytecode = True

# Source
from helper import onnxSessionBuild, lineBuild, blockText, gridPositionList, gridRowList, textJoin, boxIntersection, boxCenterInsideCheck, boxExpand, levelSpaceWord, levelSpaceGap

class Table:
    def _imageCrop(self, image, scale, bboxList):
        imageHeight, imageWidth = image.shape[0:2]

        ratio = self.imageSizePage / float(imageHeight)

        imageResized = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), (int(imageWidth * ratio), self.imageSizePage), interpolation=cv2.INTER_AREA)

        imageCrop = imageResized[max(0, round(bboxList[1] * scale * ratio)):round(bboxList[3] * scale * ratio), max(0, round(bboxList[0] * scale * ratio)):round(bboxList[2] * scale * ratio)]

        tensor = cv2.resize((imageCrop.astype(numpy.float32) - 255.0 * self.normalizeMeanList) / self.normalizeStandardList, (self.imageSizeTable, self.imageSizeTable), interpolation=cv2.INTER_LINEAR)

        return numpy.expand_dims(tensor.transpose((2, 1, 0)) / 255.0, axis=0).astype(numpy.float32)

    def _tagDecode(self, memory):
        tagList = [self.tagObject["<start>"]]
        hiddenList = []
        mergeObject = {}

        buffer = numpy.zeros((self.countLayer, self.countStep, 1, self.sizeHidden), dtype=numpy.float32)

        isSkip = True
        isSpan = False

        indexSpan = -1

        while len(tagList) < self.countStep:
            position = len(tagList) - 1

            logit, hidden, state = self.onnxSessionDecoder.run(None, {"tag": numpy.array([tagList[position]], dtype=numpy.int64), "position": numpy.array([position], dtype=numpy.int64), "memory": memory, "buffer": buffer})

            buffer[:, position] = state[:, 0]

            tag = int(numpy.argmax(logit[0]))

            if tag == self.tagObject["xcel"]:
                tag = self.tagObject["lcel"]

            if tagList[position] == self.tagObject["ucel"] and tag == self.tagObject["lcel"]:
                tag = self.tagObject["fcel"]

            if tag == self.tagObject["<end>"]:
                break

            if isSkip == False and tag != self.tagObject["lcel"]:
                if isSpan:
                    mergeObject[indexSpan] = len(hiddenList)

                hiddenList.append(hidden[0])

            if tag != self.tagObject["lcel"]:
                isSpan = False
            elif isSpan == False:
                isSpan = True

                indexSpan = len(hiddenList)

                hiddenList.append(hidden[0])

            isSkip = tag in self.tagSkipList

            tagList.append(tag)

        return {"tagList": tagList[1:], "hiddenList": hiddenList, "mergeObject": mergeObject}

    def _boxDecode(self, box, hiddenList, mergeObject):
        coordinateList = []

        for a in range(0, len(hiddenList), self.countBatch):
            hiddenBatch = numpy.zeros((self.countBatch, self.sizeHidden), dtype=numpy.float32)

            count = len(hiddenList[a:a + self.countBatch])

            hiddenBatch[0:count] = numpy.stack(hiddenList[a:a + self.countBatch])

            coordinateList += list(self.onnxSessionBox.run(None, {"box": box, "hidden": hiddenBatch})[1][0:count])

        resultList = []

        indexSkipList = []

        for a in range(len(coordinateList)):
            first = coordinateList[a]

            left = first[0] - first[2] / 2
            top = first[1] - first[3] / 2
            right = first[0] + first[2] / 2
            bottom = first[1] + first[3] / 2

            if a in mergeObject:
                second = coordinateList[mergeObject[a]]

                indexSkipList.append(mergeObject[a])

                top = min(top, second[1] - second[3] / 2)
                right = second[0] + second[2] / 2
                bottom = second[1] + second[3] / 2

            if a in mergeObject or a not in indexSkipList:
                resultList.append([float(left), float(top), float(right), float(bottom)])

        return resultList

    def _cellBuild(self, tagList, boxList, bboxList):
        rowTagList = [[]]

        for a in range(len(tagList)):
            if tagList[a] == self.tagObject["nl"]:
                rowTagList.append([])
            else:
                rowTagList[len(rowTagList) - 1].append(tagList[a])

        rowTagList = [rowObject for rowObject in rowTagList if len(rowObject) > 0]

        width = bboxList[2] - bboxList[0]
        height = bboxList[3] - bboxList[1]

        cellList = []

        for a in range(len(rowTagList)):
            for b in range(len(rowTagList[a])):
                if rowTagList[a][b] not in self.tagCellList:
                    continue

                columnSpan = 1

                while b + columnSpan < len(rowTagList[a]) and rowTagList[a][b + columnSpan] == self.tagObject["lcel"]:
                    columnSpan += 1

                rowSpan = 1

                while a + rowSpan < len(rowTagList) and b < len(rowTagList[a + rowSpan]) and rowTagList[a + rowSpan][b] == self.tagObject["ucel"]:
                    rowSpan += 1

                cellObject = {"row": a, "column": b, "rowSpan": rowSpan, "columnSpan": columnSpan, "bbox": None, "isGood": False, "itemList": []}

                if len(cellList) < len(boxList):
                    boxObject = boxList[len(cellList)]

                    cellObject["bbox"] = [bboxList[0] + boxObject[0] * width, bboxList[1] + boxObject[1] * height, bboxList[0] + boxObject[2] * width, bboxList[1] + boxObject[3] * height]

                cellList.append(cellObject)

        return {"cellList": cellList, "countRow": len(rowTagList), "countColumn": max([len(rowObject) for rowObject in rowTagList] + [0])}

    def _cellGroup(self, boxCellList, itemList):
        cellList = [{"bbox": boxCellList[a], "itemList": []} for a in range(len(boxCellList))]

        outsideList = []

        for a in range(len(itemList)):
            cellObject = self._cellMatch(cellList, itemList[a]["bbox"])

            if cellObject == None:
                outsideList.append(itemList[a])
            else:
                cellObject["itemList"].append(itemList[a])

        resultList = [cellObject for cellObject in cellList if len(cellObject["itemList"]) > 0]

        for a in range(len(resultList)):
            cellObject = resultList[a]

            cellObject["bboxCell"] = cellObject["bbox"]
            cellObject["bbox"] = list(cellObject["itemList"][0]["bbox"])

            for b in range(1, len(cellObject["itemList"])):
                cellObject["bbox"] = boxExpand(cellObject["bbox"], cellObject["itemList"][b]["bbox"])

        return {"cellList": resultList, "outsideList": outsideList}

    def _separatorList(self, cellList, indexStart, indexEnd, count, boundaryList):
        edgeList = sorted(set([cellObject["bbox"][indexStart] for cellObject in cellList] + [cellObject["bbox"][indexEnd] for cellObject in cellList]))

        runList = []

        for a in range(len(edgeList) - 1):
            middle = (edgeList[a] + edgeList[a + 1]) / 2

            cover = len([cellObject for cellObject in cellList if cellObject["bbox"][indexStart] < middle and cellObject["bbox"][indexEnd] > middle])

            if len(runList) > 0 and runList[len(runList) - 1]["cover"] == cover:
                runList[len(runList) - 1]["end"] = edgeList[a + 1]
            else:
                runList.append({"cover": cover, "start": edgeList[a], "end": edgeList[a + 1]})

        valleyList = [runList[a] for a in range(1, len(runList) - 1) if runList[a]["cover"] < runList[a - 1]["cover"] and runList[a]["cover"] < runList[a + 1]["cover"]]

        if len(valleyList) < count:
            return None

        valleyList.sort(key=lambda runObject: (runObject["cover"], runObject["start"] - runObject["end"]))

        valleyList = valleyList[0:count] + [runObject for runObject in valleyList[count:] if len([boundary for boundary in boundaryList if boundary >= runObject["start"] and boundary <= runObject["end"]]) > 0]

        return sorted((runObject["start"] + runObject["end"]) / 2 for runObject in valleyList)

    def _centerList(self, cellList, indexStart, separatorList, indexEnd):
        edgeList = [min(cellObject["bbox"][indexStart] for cellObject in cellList)] + separatorList + [max(cellObject["bbox"][indexEnd] for cellObject in cellList)]

        return [(edgeList[a] + edgeList[a + 1]) / 2 for a in range(len(edgeList) - 1)]

    def _bandIndex(self, separatorList, value):
        return len([separator for separator in separatorList if separator < value])

    def _spanFind(self, centerList, start, end, separatorList, center):
        indexList = [a for a in range(len(centerList)) if centerList[a] > start and centerList[a] < end]

        if len(indexList) == 0:
            indexList = [self._bandIndex(separatorList, center)]

        return {"index": indexList[0], "span": indexList[len(indexList) - 1] - indexList[0] + 1}

    def _cellPosition(self, cellList, separatorColumnList, separatorRowList):
        centerColumnList = self._centerList(cellList, 0, separatorColumnList, 2)
        centerRowList = self._centerList(cellList, 1, separatorRowList, 3)

        for a in range(len(cellList)):
            cellObject = cellList[a]

            columnObject = self._spanFind(centerColumnList, cellObject["bboxCell"][0], cellObject["bboxCell"][2], separatorColumnList, (cellObject["bbox"][0] + cellObject["bbox"][2]) / 2)
            rowObject = self._spanFind(centerRowList, cellObject["bboxCell"][1], cellObject["bboxCell"][3], separatorRowList, (cellObject["bbox"][1] + cellObject["bbox"][3]) / 2)

            cellObject["column"] = columnObject["index"]
            cellObject["columnSpan"] = columnObject["span"]
            cellObject["row"] = rowObject["index"]
            cellObject["rowSpan"] = rowObject["span"]

    def _outsideAssign(self, outsideList, separatorRowList, separatorColumnList, cellList):
        for a in range(len(outsideList)):
            bboxList = outsideList[a]["bbox"]

            row = self._bandIndex(separatorRowList, (bboxList[1] + bboxList[3]) / 2)
            column = self._bandIndex(separatorColumnList, (bboxList[0] + bboxList[2]) / 2)

            cellFoundList = [cellObject for cellObject in cellList if cellObject["row"] <= row and cellObject["row"] + cellObject["rowSpan"] > row and cellObject["column"] <= column and cellObject["column"] + cellObject["columnSpan"] > column]

            if len(cellFoundList) == 0:
                cellFoundList = [{"row": row, "column": column, "rowSpan": 1, "columnSpan": 1, "itemList": []}]

                cellList.append(cellFoundList[0])

            cellFoundList[0]["itemList"].append(outsideList[a])

    def _cellResolve(self, cellList):
        resultList = []

        originObject = {}

        cellSortedList = sorted(cellList, key=lambda cellObject: (cellObject["row"], cellObject["column"]))

        for a in range(len(cellSortedList)):
            key = (cellSortedList[a]["row"], cellSortedList[a]["column"])

            if key in originObject:
                originObject[key]["itemList"] += cellSortedList[a]["itemList"]

                continue

            originObject[key] = cellSortedList[a]

            resultList.append(cellSortedList[a])

        coveredList = []

        for a in range(len(resultList)):
            positionList = gridPositionList(resultList[a])

            if len([position for position in positionList if position in originObject or position in coveredList]) > 0:
                resultList[a]["rowSpan"] = 1
                resultList[a]["columnSpan"] = 1

                continue

            coveredList += positionList

        return resultList

    def _underlineCheck(self, itemList, bboxRuleList):
        aboveList = [itemObject for itemObject in itemList if bboxRuleList[1] > (itemObject["bbox"][1] + itemObject["bbox"][3]) / 2 and bboxRuleList[1] <= itemObject["bbox"][3] + itemObject["size"] * levelSpaceGap and min(itemObject["bbox"][2], bboxRuleList[2]) > max(itemObject["bbox"][0], bboxRuleList[0])]

        if len(aboveList) == 0:
            return False

        tolerance = min(itemObject["size"] for itemObject in aboveList) * levelSpaceGap

        return bboxRuleList[0] >= min(itemObject["bbox"][0] for itemObject in aboveList) - tolerance and bboxRuleList[2] <= max(itemObject["bbox"][2] for itemObject in aboveList) + tolerance

    def _ruleBoundaryList(self, itemList, ruleList, bboxList, index):
        resultList = []

        margin = min(itemObject["size"] for itemObject in itemList) * levelSpaceWord

        for a in range(len(ruleList)):
            bboxRuleList = ruleList[a]["bbox"]

            if min(bboxRuleList[2], bboxList[2] + margin) >= max(bboxRuleList[0], bboxList[0] - margin) and min(bboxRuleList[3], bboxList[3] + margin) >= max(bboxRuleList[1], bboxList[1] - margin) and self._underlineCheck(itemList, bboxRuleList) == False:
                resultList += [bboxRuleList[index], bboxRuleList[index + 2]]

        return resultList

    def _gridBuild(self, boxCellList, itemList, countColumn, structureObject, ruleList, bboxList, countRow):
        groupObject = self._cellGroup(boxCellList, itemList)

        cellList = groupObject["cellList"]

        if len(cellList) == 0:
            return None

        separatorColumnList = self._separatorList(cellList, 0, 2, countColumn - 1, structureObject["boundaryColumnList"] + self._ruleBoundaryList(itemList, ruleList, bboxList, 0))
        separatorRowList = self._separatorList(cellList, 1, 3, countRow - 1, structureObject["boundaryRowList"] + self._ruleBoundaryList(itemList, ruleList, bboxList, 1))

        if separatorColumnList == None or separatorRowList == None:
            return None

        self._cellPosition(cellList, separatorColumnList, separatorRowList)

        self._outsideAssign(groupObject["outsideList"], separatorRowList, separatorColumnList, cellList)

        return self._cellResolve(cellList)

    def _cellMatch(self, cellList, bboxList):
        result = None

        coverBest = 0

        for a in range(len(cellList)):
            if cellList[a]["bbox"] == None:
                continue

            cover = boxIntersection(bboxList, cellList[a]["bbox"])

            if cover > coverBest:
                result = cellList[a]
                coverBest = cover

        if result == None or boxCenterInsideCheck(bboxList, result["bbox"]) == False:
            return None

        return result

    def _matchList(self, itemList, cellList):
        resultList = []

        for a in range(len(itemList)):
            cellObject = self._cellMatch(cellList, itemList[a]["bbox"])

            if cellObject != None:
                cellObject["isGood"] = True

            resultList.append(cellObject)

        return resultList

    def _bandColumnList(self, countColumn, cellList):
        resultList = []

        for a in range(countColumn):
            startList = sorted(cellObject["bbox"][0] for cellObject in cellList if cellObject["isGood"] and cellObject["column"] == a and cellObject["columnSpan"] == 1)
            endList = sorted(cellObject["bbox"][2] for cellObject in cellList if cellObject["isGood"] and cellObject["column"] == a and cellObject["columnSpan"] == 1)

            resultList.append([startList[len(startList) // 2], endList[len(endList) // 2]] if len(startList) > 0 else None)

        return resultList

    def _bandRowList(self, countRow, cellList):
        resultList = []

        for a in range(countRow):
            startList = [cellObject["bbox"][1] for cellObject in cellList if cellObject["isGood"] and cellObject["row"] == a and cellObject["rowSpan"] == 1]
            endList = [cellObject["bbox"][3] for cellObject in cellList if cellObject["isGood"] and cellObject["row"] == a and cellObject["rowSpan"] == 1]

            resultList.append([min(startList), max(endList)] if len(startList) > 0 else None)

        return resultList

    def _bandFind(self, bandList, start, end):
        result = -1

        overlapBest = None

        for a in range(len(bandList)):
            if bandList[a] == None:
                continue

            overlap = min(end, bandList[a][1]) - max(start, bandList[a][0])

            if overlapBest == None or overlap > overlapBest:
                result = a
                overlapBest = overlap

        return result

    def _textAssign(self, tableObject, itemList, matchList, bandColumnList, bandRowList):
        cellList = tableObject["cellList"]

        originObject = {}

        for a in range(len(cellList)):
            for b in range(cellList[a]["rowSpan"]):
                for c in range(cellList[a]["columnSpan"]):
                    originObject[(cellList[a]["row"] + b, cellList[a]["column"] + c)] = cellList[a]

        for a in range(len(itemList)):
            if matchList[a] != None:
                matchList[a]["itemList"].append(itemList[a])

                continue

            bboxList = itemList[a]["bbox"]

            column = self._bandFind(bandColumnList, bboxList[0], bboxList[2])

            bandList = []

            for b in range(tableObject["countRow"]):
                if (b, column) in originObject and originObject[(b, column)]["isGood"]:
                    bandList.append([originObject[(b, column)]["bbox"][1], originObject[(b, column)]["bbox"][3]])
                else:
                    bandList.append(bandRowList[b])

            row = self._bandFind(bandList, bboxList[1], bboxList[3])

            if (row, column) not in originObject:
                originObject[(row, column)] = {"row": row, "column": column, "rowSpan": 1, "columnSpan": 1, "bbox": None, "isGood": False, "itemList": []}

                cellList.append(originObject[(row, column)])

            originObject[(row, column)]["itemList"].append(itemList[a])

    def _rowList(self, cellList, countRow, countColumn):
        for a in range(len(cellList)):
            cellList[a]["text"] = blockText(cellList[a]["itemList"])

        return gridRowList(cellList, countRow, countColumn)

    def execute(self, image, scale, bboxList, boxCellList, itemList, structureObject, ruleList):
        memory, box = self.onnxSessionEncoder.run(None, {"image": self._imageCrop(image, scale, bboxList)})

        decodeObject = self._tagDecode(memory)

        tableObject = self._cellBuild(decodeObject["tagList"], self._boxDecode(box, decodeObject["hiddenList"], decodeObject["mergeObject"]), bboxList)

        cellList = self._gridBuild(boxCellList, itemList, tableObject["countColumn"], structureObject, ruleList, bboxList, tableObject["countRow"])

        if cellList != None:
            return self._rowList(cellList, max(cellObject["row"] + cellObject["rowSpan"] for cellObject in cellList), max(cellObject["column"] + cellObject["columnSpan"] for cellObject in cellList))

        cellList = tableObject["cellList"]

        matchList = self._matchList(itemList, cellList)

        bandColumnList = self._bandColumnList(tableObject["countColumn"], cellList)
        bandRowList = self._bandRowList(tableObject["countRow"], cellList)

        if len([band for band in bandColumnList if band != None]) == 0 or len([band for band in bandRowList if band != None]) == 0:
            return []

        self._textAssign(tableObject, itemList, matchList, bandColumnList, bandRowList)

        return self._rowList(cellList, tableObject["countRow"], tableObject["countColumn"])

    def __init__(self):
        pathModel = f"{os.path.dirname(os.path.abspath(__file__))}/model/docling/TableFormer"

        self.imageSizePage = 1024
        self.imageSizeTable = 448

        self.normalizeMeanList = numpy.array([0.94247851, 0.94254675, 0.94292611], dtype=numpy.float32)
        self.normalizeStandardList = numpy.array([0.17910956, 0.17940403, 0.17931663], dtype=numpy.float32)

        self.countStep = 1024
        self.countLayer = 6
        self.countBatch = 32
        self.sizeHidden = 512

        self.tagObject = {"<pad>": 0, "<unk>": 1, "<start>": 2, "<end>": 3, "ecel": 4, "fcel": 5, "lcel": 6, "ucel": 7, "xcel": 8, "nl": 9, "ched": 10, "rhed": 11, "srow": 12}
        self.tagCellList = [self.tagObject["ecel"], self.tagObject["fcel"], self.tagObject["ched"], self.tagObject["rhed"], self.tagObject["srow"]]
        self.tagSkipList = [self.tagObject["nl"], self.tagObject["ucel"], self.tagObject["xcel"]]

        self.onnxSessionEncoder = onnxSessionBuild(f"{pathModel}/tableFormer_encoder.onnx")
        self.onnxSessionDecoder = onnxSessionBuild(f"{pathModel}/tableFormer_decoder.onnx")
        self.onnxSessionBox = onnxSessionBuild(f"{pathModel}/tableFormer_box.onnx")
