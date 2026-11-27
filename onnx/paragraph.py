import sys

sys.dont_write_bytecode = True

# Source
from helper import textJoin, sentenceEndCheck, labelFloatList, labelText, labelHeader, levelSpaceGap

class Paragraph:
    def _floatCheck(self, itemObject):
        return itemObject["kind"] in self.kindFloatList or itemObject["label"] in labelFloatList or itemObject["label"] == labelHeader

    def _characterWidth(self, lineObject):
        return (lineObject["bbox"][2] - lineObject["bbox"][0]) / len(lineObject["text"])

    def _openCheck(self, itemObject):
        if itemObject["kind"] != "text" or itemObject["label"] != labelText:
            return False

        lineList = itemObject["lineList"]

        if len(lineList) < 2 or sentenceEndCheck(itemObject["text"]):
            return False

        lineObject = lineList[len(lineList) - 1]

        return lineObject["bbox"][2] + self._characterWidth(lineObject) >= min(lineList[a]["bbox"][2] for a in range(len(lineList) - 1))

    def _neighborFind(self, index, step, itemList):
        result = index + step

        while result >= 0 and result < len(itemList):
            if self._floatCheck(itemList[result]) == False and itemList[result]["group"] == itemList[index]["group"]:
                return result

            result += step

        return -1

    def _followCheck(self, itemObject):
        if itemObject["kind"] != "text" or itemObject["label"] != labelText:
            return False

        lineList = itemObject["lineList"]

        return len(lineList) < 2 or lineList[0]["bbox"][0] <= min(lineList[a]["bbox"][0] for a in range(1, len(lineList)))

    def _overlapCheck(self, itemObject, itemOtherObject):
        return min(itemObject["bbox"][2], itemOtherObject["bbox"][2]) > max(itemObject["bbox"][0], itemOtherObject["bbox"][0])

    def _pitchList(self, lineList):
        return [lineList[a]["bbox"][3] - lineList[a - 1]["bbox"][3] for a in range(1, len(lineList))]

    def _stackCheck(self, itemObject, itemNextObject):
        if itemObject["page"] != itemNextObject["page"] or self._overlapCheck(itemObject, itemNextObject) == False:
            return False

        lineList = itemObject["lineList"]
        lineNextList = itemNextObject["lineList"]

        lineObject = lineList[len(lineList) - 1]

        if lineNextList[0]["bbox"][1] <= lineObject["bbox"][1]:
            return False

        pitchList = self._pitchList(lineList) + self._pitchList(lineNextList)

        return lineNextList[0]["bbox"][3] - lineObject["bbox"][3] - max(pitchList) < min(lineOtherObject["bbox"][3] - lineOtherObject["bbox"][1] for lineOtherObject in lineList + lineNextList) * levelSpaceGap

    def _edgeCheck(self, itemObject, itemList, isLast):
        center = (itemObject["bbox"][1] + itemObject["bbox"][3]) / 2

        for a in range(len(itemList)):
            itemOtherObject = itemList[a]

            if itemOtherObject is itemObject or itemOtherObject["page"] != itemObject["page"] or self._floatCheck(itemOtherObject) or self._overlapCheck(itemObject, itemOtherObject) == False:
                continue

            centerOther = (itemOtherObject["bbox"][1] + itemOtherObject["bbox"][3]) / 2

            if (isLast and centerOther > center) or (isLast == False and centerOther < center):
                return False

        return True

    def _jumpCheck(self, itemObject, itemNextObject, itemList):
        if itemObject["page"] == itemNextObject["page"] and itemNextObject["bbox"][0] <= itemObject["bbox"][2]:
            return False

        return self._edgeCheck(itemObject, itemList, True) and self._edgeCheck(itemNextObject, itemList, False)

    def _joinCheck(self, itemObject, itemNextObject, itemList):
        if self._openCheck(itemObject) == False or self._followCheck(itemNextObject) == False:
            return False

        return self._stackCheck(itemObject, itemNextObject) or self._jumpCheck(itemObject, itemNextObject, itemList)

    def _lineMatchCheck(self, itemObject, itemNextObject):
        lineObject = itemObject["lineList"][len(itemObject["lineList"]) - 1]
        lineNextObject = itemNextObject["lineList"][0]

        width = self._characterWidth(lineObject)

        return abs(lineNextObject["bbox"][0] - lineObject["bbox"][0]) <= width and abs(lineNextObject["bbox"][2] - lineObject["bbox"][2]) <= width

    def _headFind(self, itemList, index):
        itemObject = itemList[index]

        for a in range(index + 1, len(itemList)):
            itemNextObject = itemList[a]

            if itemNextObject["page"] > itemObject["page"] + 1:
                break

            if itemNextObject["page"] == itemObject["page"] + 1 and itemNextObject["label"] == labelHeader and self._lineMatchCheck(itemObject, itemNextObject):
                return a

        return -1

    def _pageFind(self, itemList, index):
        itemObject = itemList[index]

        for a in range(index + 1, len(itemList)):
            itemNextObject = itemList[a]

            if itemNextObject["group"] != itemObject["group"]:
                continue

            if itemNextObject["page"] > itemObject["page"] + 1:
                break

            if itemNextObject["page"] == itemObject["page"] or self._floatCheck(itemNextObject) or itemNextObject["kind"] != "text" or self._overlapCheck(itemObject, itemNextObject) == False or self._edgeCheck(itemNextObject, itemList, False) == False:
                continue

            return a

        return -1

    def _targetFind(self, itemList, index):
        itemObject = itemList[index]

        if self._openCheck(itemObject) == False:
            return -1

        indexHead = self._headFind(itemList, index)

        if indexHead != -1 and self._edgeCheck(itemObject, itemList, True):
            return indexHead

        indexNext = self._neighborFind(index, 1, itemList)

        if indexNext != -1 and self._joinCheck(itemObject, itemList[indexNext], itemList):
            return indexNext

        indexPage = self._pageFind(itemList, index)

        if indexPage == -1 or self._followCheck(itemList[indexPage]) == False or self._edgeCheck(itemObject, itemList, True) == False or self._joinCheck(itemList[self._neighborFind(indexPage, -1, itemList)], itemList[indexPage], itemList):
            return -1

        return indexPage

    def execute(self, itemList):
        resultList = list(itemList)

        index = 0

        while index < len(resultList):
            indexTarget = self._targetFind(resultList, index)

            if indexTarget == -1:
                index += 1

                continue

            itemObject = resultList[index]

            itemNextObject = resultList.pop(indexTarget)

            itemObject["text"] = textJoin(itemObject["text"], itemNextObject["text"])
            itemObject["lineList"] = itemNextObject["lineList"]
            itemObject["page"] = itemNextObject["page"]
            itemObject["bbox"] = itemNextObject["bbox"]

        return resultList

    def __init__(self):
        self.kindFloatList = ["table"]
