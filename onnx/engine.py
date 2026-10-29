import sys
import os
import cv2
import json
import time
import zipfile

sys.dont_write_bytecode = True

# Source
import layout
import table
import ocr
import form
import raster
import office
import markdown

class Engine:
    def _packageZip(self, pathOutput):
        pathMedia = f"{pathOutput}media/"

        with zipfile.ZipFile(f"{pathOutput}result.zip", "w") as zipFile:
            zipFile.write(f"{pathOutput}result.md", "result.md", zipfile.ZIP_DEFLATED)

            if os.path.isdir(pathMedia):
                fileNameList = sorted(os.listdir(pathMedia))

                for a in range(len(fileNameList)):
                    zipFile.write(f"{pathMedia}{fileNameList[a]}", f"media/{fileNameList[a]}", zipfile.ZIP_STORED)

    def _extensionCategory(self, extension):
        for category in self.extensionObject:
            if extension in self.extensionObject[category]:
                return category

        return ""

    def _extensionAllowed(self):
        resultObject = {"image": [], "pdf": [], "office": []}

        mimeTypeList = json.loads(os.environ["MS_FDE_MIME_TYPE"])

        for a in range(len(mimeTypeList)):
            extension = f".{mimeTypeList[a].split('/')[1]}"

            if mimeTypeList[a].startswith("image/"):
                resultObject["image"].append(extension)

                continue

            if mimeTypeList[a] == "application/pdf":
                resultObject["pdf"].append(extension)

                continue

            if mimeTypeList[a] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                resultObject["office"].append(".docx")

                continue

            if mimeTypeList[a] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
                resultObject["office"].append(".xlsx")

                continue

            if mimeTypeList[a] == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
                resultObject["office"].append(".pptx")

        return resultObject

    def execute(self, pathInput, pathOutput, job, password):
        timeStart = time.perf_counter()

        extension = os.path.splitext(pathInput)[1].lower()

        category = self._extensionCategory(extension)

        if category == "":
            return {"response": {"state": "ko", "message": "Extension not supported."}}

        os.makedirs(pathOutput, exist_ok=True)

        if self.isDebug:
            for a in range(len(self.debugNameList)):
                os.makedirs(f"{pathOutput}debug/{self.debugNameList[a]}/", exist_ok=True)

        if category == "image":
            resultObject = self.raster.image.execute(pathInput, pathOutput, job)
        elif category == "pdf":
            resultObject = self.raster.pdf.execute(password, pathInput, pathOutput, job)
        else:
            resultObject = self.office.execute(pathInput, pathOutput, extension)

        if "message" in resultObject:
            return {"response": {"state": "ko", "message": resultObject["message"]}}

        if resultObject["pageCount"] == 0:
            return {"response": {"state": "ko", "message": "File not readable."}}

        resultObject["markdown"] = self.markdown.execute(resultObject, extension)

        if self.isDebug:
            with open(f"{pathOutput}debug/result.json", "w", encoding="utf-8") as file:
                json.dump({"layoutList": resultObject["layoutList"], "tableList": resultObject["tableList"], "itemList": resultObject["itemList"]}, file, ensure_ascii=False, indent=2)

        with open(f"{pathOutput}result.md", "w", encoding="utf-8") as file:
            file.write(resultObject["markdown"])

        self._packageZip(pathOutput)

        timeEnd = time.perf_counter() - timeStart

        print(f"\nengine.py - Time: {round(timeEnd, 3)} - {os.path.basename(pathInput)} - Page: {resultObject['pageCount']}")

        return {"response": {"state": "ok", "message": "Task completed."}}

    def __init__(self):
        self.isDebug = os.environ["MS_FDE_IS_DEBUG"] == "true"

        self.countThread = 0

        self.extensionObject = self._extensionAllowed()

        self.debugNameList = ["layout", "table", "ocr", "page"]

        self.layout = layout.Layout(self.isDebug)
        self.table = table.Table(self.isDebug)
        self.ocr = ocr.Ocr(self.isDebug)
        self.form = form.Form()
        self.raster = raster.Raster(self.isDebug, self.layout, self.table, self.ocr, self.form)
        self.office = office.Office(self.isDebug)
        self.markdown = markdown.Markdown(self.extensionObject, self.office)

        cv2.setUseOptimized(True)
        cv2.setNumThreads(self.countThread)
