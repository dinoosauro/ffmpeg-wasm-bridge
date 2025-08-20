import asyncio
import sys
import os
import copy
from server import FFmpegOperation, FFmpegServer, FileBridge
import subprocess

class __test_files():
    version = "0.11.x-mt"
    def __init__(self, version = "0.11.x-mt"):
        self.version = version
    async def start(self):
        self.server = FFmpegServer()
        await self.server.start()
        if len(sys.argv) > 4 and sys.argv[4] == "--autorun-chrome": # Open Chrome in headless mode. This is the only way we can run this script on GitHub Actions
            subprocess.Popen(["google-chrome", "--headless", "--no-sandbox", "--disable-gpu", f"http://localhost:{self.server._actual_port}/"])
        self.operation = FFmpegOperation(self.server)
        await self.server._connected_to_ws
    def check_valid_file(self, file):
        return os.path.isfile(file) and os.stat(file).st_size > 64_000
    async def test_normal_operation(self):
        # Just a normal operation. Let's convert a file to AAC
        await self.operation.run(["-i", sys.argv[1], "-acodec", "aac", "-b:a", "96k", "-vn", "__FFmpegWrapper_Test1.m4a"])
        if not self.check_valid_file(f"{os.getcwd()}{os.path.sep}__FFmpegWrapper_Test1.m4a"): raise Exception("Failed normal conversion!")

    async def test_relative_file_name(self):
        relative_name = sys.argv[1][(sys.argv[1].rfind(os.path.sep) + 1):]
        await self.operation.run(["-i", relative_name, "-acodec", "aac", "-b:a", "96k", "-vn", "__FFmpegWrapper_Test2.m4a"], [FileBridge(sys.argv[1], relative_name)])
        if not self.check_valid_file(f"{os.getcwd()}{os.path.sep}__FFmpegWrapper_Test2.m4a"): raise Exception("Failed relative path!")

    async def test_image_merge(self):
        with open(f"{os.getcwd()}{os.path.sep}__FFmpegWrapper_Test3.txt", "w") as file:
            file.writelines(["file '0.jpg'\n", "file '0.jpg'\n", "file '1.jpg'\n", "file '1.jpg'\n", "file '1.jpg'"])
        bridgeArr = [FileBridge(sys.argv[2], None, "0.jpg"), FileBridge(sys.argv[3], None, "1.jpg")]
        bridgeArrExtended = copy.deepcopy(bridgeArr)
        bridgeArrExtended.append(FileBridge(f"{os.getcwd()}{os.path.sep}__FFmpegWrapper_Test3.txt", "__FFmpegWrapper_Test3.txt"))
        await self.operation.run(["-f", "concat", "-safe", "0", "-r", "1", "-i", "__FFmpegWrapper_Test3.txt", "__FFmpegWrapper_Test3.mp4"], files=bridgeArrExtended)
        await self.operation.delete_files(bridgeArr)
        if not self.check_valid_file(f"{os.getcwd()}{os.path.sep}__FFmpegWrapper_Test3.mp4"): raise Exception("Failed image merge!")

    def remove_everything(self):
        for file in [f"{os.getcwd()}{os.path.sep}__FFmpegWrapper_Test3.mp4", 
                    f"{os.getcwd()}{os.path.sep}__FFmpegWrapper_Test1.m4a",
                    f"{os.getcwd()}{os.path.sep}__FFmpegWrapper_Test3.txt",
                    f"{os.getcwd()}{os.path.sep}__FFmpegWrapper_Test2.m4a"]:
            if os.path.exists(file): 
                os.remove(file)


async def __tests():
    for ffmpeg_version in ["0.12.x-mt", "0.12.x-st", "0.11.x-mt"]:
        test_class = __test_files(ffmpeg_version)
        await test_class.start()
        test_class.operation = FFmpegOperation(test_class.server, ffmpeg_version)
        await test_class.test_normal_operation()
        await test_class.test_relative_file_name()
        await test_class.test_image_merge()
        await test_class.operation.reload_ffmpeg()
        os.remove(f"{os.getcwd()}{os.path.sep}__FFmpegWrapper_Test1.m4a")
        await test_class.test_normal_operation()
        os.remove(f"{os.getcwd()}{os.path.sep}__FFmpegWrapper_Test1.m4a")    
        os.remove(f"{os.getcwd()}{os.path.sep}__FFmpegWrapper_Test2.m4a")
        await test_class.test_normal_operation()
        test_class.remove_everything()
    return True

if __name__ == "__main__":
    asyncio.run(__tests())
