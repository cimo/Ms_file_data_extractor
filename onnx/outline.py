import sys

sys.dont_write_bytecode = True

# Source
from helper import levelTitleMaximum

class Outline:
    def execute(self, itemList):
        titleList = [itemObject for itemObject in itemList if itemObject["kind"] == "title"]

        sizeList = sorted(set(titleObject["size"] for titleObject in titleList), reverse=True)

        for a in range(len(titleList)):
            titleList[a]["level"] = min(levelTitleMaximum, sizeList.index(titleList[a]["size"]) + 1)

        return itemList
