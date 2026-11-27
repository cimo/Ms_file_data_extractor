import sys
import os
import cv2
import numpy

sys.dont_write_bytecode = True

# Source
from helper import onnxSessionBuild, tensorNormalize

class Orientation:
    def execute(self, image):
        imageHeight, imageWidth = image.shape[0:2]

        ratio = self.sizeResize / min(imageHeight, imageWidth)

        imageResized = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), (max(self.sizeCrop, int(round(imageWidth * ratio))), max(self.sizeCrop, int(round(imageHeight * ratio)))))

        top = int((imageResized.shape[0] - self.sizeCrop) / 2)
        left = int((imageResized.shape[1] - self.sizeCrop) / 2)

        scoreList = self.onnxSession.run(None, {"x": tensorNormalize(imageResized[top:top + self.sizeCrop, left:left + self.sizeCrop], self.meanList, self.standardList)})[0][0]

        return self.angleList[int(numpy.argmax(scoreList))]

    def __init__(self):
        self.sizeResize = 256
        self.sizeCrop = 224

        self.angleList = [0, 90, 180, 270]

        self.meanList = numpy.array([0.485, 0.456, 0.406], dtype=numpy.float32)
        self.standardList = numpy.array([0.229, 0.224, 0.225], dtype=numpy.float32)

        self.onnxSession = onnxSessionBuild(f"{os.path.dirname(os.path.abspath(__file__))}/model/paddle/PP-LCNet_x1_0_doc_ori/pp-lcNet_x1_0_doc_ori.onnx")
