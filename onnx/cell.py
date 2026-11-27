import sys
import os
import cv2

sys.dont_write_bytecode = True

# Source
from helper import onnxSessionBuild, detrDetect, boxCenterInsideCheck, levelSpaceGap

class Cell:
    def _boxList(self, imageRgb, onnxSession, left, top, scale):
        resultList = []

        detectionList = detrDetect(imageRgb, self.imageSize, cv2.INTER_CUBIC, onnxSession)

        for a in range(len(detectionList)):
            if detectionList[a]["score"] < self.scoreThreshold:
                continue

            bboxList = detectionList[a]["bbox"]

            resultList.append([(left + bboxList[0]) / scale, (top + bboxList[1]) / scale, (left + bboxList[2]) / scale, (top + bboxList[3]) / scale])

        return resultList

    def _countSingle(self, itemList, boxList):
        result = 0

        for a in range(len(itemList)):
            if len([bboxList for bboxList in boxList if boxCenterInsideCheck(itemList[a]["bbox"], bboxList)]) == 1:
                result += 1

        return result

    def _ruleSplit(self, itemList, bboxList, ruleList):
        insideList = [itemObject for itemObject in itemList if boxCenterInsideCheck(itemObject["bbox"], bboxList)]

        if len(insideList) < 2:
            return [bboxList]

        tolerance = min(itemObject["size"] for itemObject in insideList) * levelSpaceGap

        for a in range(len(ruleList)):
            bboxRuleList = ruleList[a]["bbox"]

            index = 0 if bboxRuleList[2] - bboxRuleList[0] < bboxRuleList[3] - bboxRuleList[1] else 1

            position = (bboxRuleList[index] + bboxRuleList[index + 2]) / 2

            if position <= bboxList[index] or position >= bboxList[index + 2] or bboxRuleList[1 - index] > bboxList[1 - index] + tolerance or bboxRuleList[3 - index] < bboxList[3 - index] - tolerance:
                continue

            beforeList = [itemObject for itemObject in insideList if itemObject["bbox"][index + 2] <= position + tolerance]
            afterList = [itemObject for itemObject in insideList if itemObject["bbox"][index] >= position - tolerance]

            if len(beforeList) > 0 and len(afterList) > 0 and len(beforeList) + len(afterList) == len(insideList):
                boxBeforeList = list(bboxList)
                boxBeforeList[index + 2] = position

                boxAfterList = list(bboxList)
                boxAfterList[index] = position

                return self._ruleSplit(itemList, boxBeforeList, ruleList) + self._ruleSplit(itemList, boxAfterList, ruleList)

        return [bboxList]

    def execute(self, image, scale, bboxList, itemList, ruleList):
        left = max(0, int(round(bboxList[0] * scale)))
        top = max(0, int(round(bboxList[1] * scale)))

        imageRgb = cv2.cvtColor(image[top:int(round(bboxList[3] * scale)), left:int(round(bboxList[2] * scale))], cv2.COLOR_BGR2RGB)

        resultList = []

        countBest = -1

        for a in range(len(self.onnxSessionList)):
            boxList = self._boxList(imageRgb, self.onnxSessionList[a], left, top, scale)

            count = self._countSingle(itemList, boxList)

            if count > countBest:
                resultList = boxList
                countBest = count

        return [boxObject for a in range(len(resultList)) for boxObject in self._ruleSplit(itemList, resultList[a], ruleList)]

    def __init__(self):
        pathModel = f"{os.path.dirname(os.path.abspath(__file__))}/model/paddle"

        self.imageSize = 640

        self.scoreThreshold = 0.5

        self.onnxSessionList = [onnxSessionBuild(f"{pathModel}/RT-DETR-L_wired_table_cell_det/rt-detr-l_wired_table_cell_det.onnx"), onnxSessionBuild(f"{pathModel}/RT-DETR-L_wireless_table_cell_det/rt-detr-l_wireless_table_cell_det.onnx")]
