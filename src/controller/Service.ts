import Fs from /* webpackIgnore: true */ "fs";
import Readline from /* webpackIgnore: true */ "readline";
import { spawn, ChildProcessWithoutNullStreams } from /* webpackIgnore: true */ "child_process";
import Express, { Request, Response } from "express";
import { RateLimitRequestHandler } from "express-rate-limit";
import { Ca } from "@cimo/authentication/dist/src/Main.js";
import { Cq } from "@cimo/queue/dist/src/Main.js";

// Source
import * as helperSrc from "../HelperSrc.js";
import * as modelService from "../model/Service.js";
import ControllerUpload from "./Upload.js";

export default class Service {
    // Variable
    private app: Express.Express;
    private limiter: RateLimitRequestHandler;
    private controllerUpload: ControllerUpload;
    private jobObject: Record<string, modelService.Ijob>;
    private cq: Cq;
    private engineProcess: ChildProcessWithoutNullStreams;
    private engineResolveObject: Record<string, () => void>;

    // Method
    private jobExpire = (uniqueId: string): void => {
        setTimeout(async () => {
            if (!this.jobObject[uniqueId]) {
                return;
            }

            delete this.jobObject[uniqueId];

            const fileOrFolderDeleteOutput = await helperSrc.fileOrFolderDelete(`${helperSrc.PATH_ROOT}${helperSrc.PATH_FILE}output/${uniqueId}/`);

            if (typeof fileOrFolderDeleteOutput !== "boolean") {
                helperSrc.writeLog("Service.ts - jobExpire() - fileOrFolderDelete()", fileOrFolderDeleteOutput.toString());
            }
        }, helperSrc.PERSISTENCE_SECOND * 1000);
    };

    private engineLine = (line: string): void => {
        const lineObject = JSON.parse(line) as modelService.IengineLine;

        const job = this.jobObject[lineObject.uniqueId];

        if (lineObject.error !== undefined) {
            job.state = "ko";
            job.message = lineObject.error;
            job.isError = true;
        } else if (lineObject.response) {
            job.state = lineObject.response.state;
            job.message = lineObject.response.message;
        }

        this.engineResolveObject[lineObject.uniqueId]();

        delete this.engineResolveObject[lineObject.uniqueId];
    };

    private engine = (uniqueId: string, pathInput: string, pathOutput: string, password: string): Promise<void> => {
        return new Promise((resolve) => {
            this.engineResolveObject[uniqueId] = resolve;

            this.engineProcess.stdin.write(`${JSON.stringify({ action: "execute", uniqueId, pathInput, pathOutput, password })}\n`);
        });
    };

    constructor(app: Express.Express, limiter: RateLimitRequestHandler) {
        this.app = app;
        this.limiter = limiter;
        this.controllerUpload = new ControllerUpload();
        this.jobObject = {};
        this.cq = new Cq(helperSrc.QUEUE);
        this.engineProcess = spawn(`${helperSrc.PATH_ROOT}.venv/bin/python3`, [`${helperSrc.PATH_ROOT}onnx/worker.py`]);
        this.engineResolveObject = {};

        this.engineProcess.stderr.pipe(Fs.createWriteStream(`${helperSrc.PATH_ROOT}${helperSrc.PATH_LOG}onnx.log`, { flags: "a" }));

        Readline.createInterface({ input: this.engineProcess.stdout }).on("line", this.engineLine);
    }

    api = (): void => {
        this.app.post("/api/extract", this.limiter, Ca.authenticationMiddleware, (request: Request, response: Response) => {
            const uniqueId = helperSrc.generateUniqueId();

            this.controllerUpload
                .execute(request, true, false, `${helperSrc.PATH_ROOT}${helperSrc.PATH_FILE}input/${uniqueId}/`)
                .then(async (resultControllerUpload) => {
                    if (resultControllerUpload.message !== "") {
                        helperSrc.responseBody({ state: "ko", message: resultControllerUpload.message }, response, 200);

                        return;
                    }

                    let fileName = "";
                    let password = "";

                    for (let a = 0; a < resultControllerUpload.formDataList.length; a++) {
                        const formData = resultControllerUpload.formDataList[a];

                        if (formData.name === "file" && formData.fileName) {
                            fileName = formData.fileName;
                        } else if (formData.name === "password" && formData.buffer) {
                            password = formData.buffer.toString();
                        }
                    }

                    const fileDetail = await helperSrc.fileDetail(fileName);

                    const pathInput = `${helperSrc.PATH_ROOT}${helperSrc.PATH_FILE}input/${uniqueId}/${fileDetail.baseName}/${fileDetail.name}`;
                    const pathInputBasename = `${helperSrc.PATH_ROOT}${helperSrc.PATH_FILE}input/${uniqueId}/`;
                    const pathOutput = `${helperSrc.PATH_ROOT}${helperSrc.PATH_FILE}output/${uniqueId}/`;

                    this.jobObject[uniqueId] = {
                        state: "",
                        message: "",
                        isError: false,
                        isCancel: false
                    };

                    this.cq.jobList.push({
                        id: uniqueId,
                        callback: async () => {
                            await this.engine(uniqueId, pathInput, pathOutput, password);

                            if (this.jobObject[uniqueId].isCancel) {
                                delete this.jobObject[uniqueId];

                                const fileOrFolderDeleteOutput = await helperSrc.fileOrFolderDelete(pathOutput);

                                if (typeof fileOrFolderDeleteOutput !== "boolean") {
                                    helperSrc.writeLog(
                                        "Service.ts - api() - post(/api/extract) - engine() - fileOrFolderDelete()",
                                        fileOrFolderDeleteOutput.toString()
                                    );
                                }
                            } else {
                                this.jobExpire(uniqueId);
                            }

                            const fileOrFolderDeleteInput = await helperSrc.fileOrFolderDelete(pathInputBasename);

                            if (typeof fileOrFolderDeleteInput !== "boolean") {
                                helperSrc.writeLog(
                                    "Service.ts - api() - post(/api/extract) - engine() - fileOrFolderDelete()",
                                    fileOrFolderDeleteInput.toString()
                                );
                            }
                        }
                    });

                    this.cq.process();

                    helperSrc.responseBody({ state: "ok", message: "", data: uniqueId }, response, 200);
                })
                .catch((error: Error) => {
                    helperSrc.writeLog("Service.ts - api() - post(/api/extract) - execute() - catch()", error.message);

                    helperSrc.responseBody({ state: "ko", message: error.message }, response, 500);
                });
        });

        this.app.post("/api/extract-check", Ca.authenticationMiddleware, async (request: Request, response: Response) => {
            const body = request.body as modelService.IapiCheckBody;

            const uniqueId = body.uniqueId;

            const isJobExists = typeof uniqueId === "string" && Object.hasOwn(this.jobObject, uniqueId);
            const job = isJobExists ? this.jobObject[uniqueId] : undefined;

            if (!job) {
                helperSrc.responseBody({ state: "ko", message: "Job not found." }, response, 200);
            } else if (job.state === "") {
                const stateQueue = this.cq.state(uniqueId);

                helperSrc.responseBody({ state: stateQueue.name, message: "", data: stateQueue.position }, response, 200);
            } else if (job.state === "ok") {
                const pathOutput = `${helperSrc.PATH_ROOT}${helperSrc.PATH_FILE}output/${uniqueId}/`;

                const fileReadStream = await helperSrc.fileReadStream(`${pathOutput}result.zip`);

                if (!Buffer.isBuffer(fileReadStream)) {
                    helperSrc.writeLog("Service.ts - api() - post(/api/extract-check) - fileReadStream()", fileReadStream.toString());

                    helperSrc.responseBody({ state: "ko", message: fileReadStream.toString() }, response, 500);
                } else {
                    helperSrc.responseBody({ state: "ok", message: "", data: fileReadStream.toString("base64") }, response, 200);
                }

                delete this.jobObject[uniqueId];

                /*const fileOrFolderDeleteOutput = await helperSrc.fileOrFolderDelete(pathOutput);

                if (typeof fileOrFolderDeleteOutput !== "boolean") {
                    helperSrc.writeLog("Service.ts - api() - post(/api/extract-check) - fileOrFolderDelete()", fileOrFolderDeleteOutput.toString());
                }*/
            } else {
                helperSrc.responseBody({ state: job.state, message: job.message }, response, job.isError ? 500 : 200);

                delete this.jobObject[uniqueId];

                const fileOrFolderDeleteOutput = await helperSrc.fileOrFolderDelete(
                    `${helperSrc.PATH_ROOT}${helperSrc.PATH_FILE}output/${uniqueId}/`
                );

                if (typeof fileOrFolderDeleteOutput !== "boolean") {
                    helperSrc.writeLog("Service.ts - api() - post(/api/extract-check) - fileOrFolderDelete()", fileOrFolderDeleteOutput.toString());
                }
            }
        });

        this.app.post("/api/extract-cancel", Ca.authenticationMiddleware, async (request: Request, response: Response) => {
            const body = request.body as modelService.IapiCancelBody;

            const uniqueId = body.uniqueId;

            const isJobExists = typeof uniqueId === "string" && Object.hasOwn(this.jobObject, uniqueId);

            if (!isJobExists) {
                helperSrc.responseBody({ state: "ko", message: "Job not found." }, response, 200);
            } else if (this.cq.remove(uniqueId)) {
                delete this.jobObject[uniqueId];

                helperSrc.responseBody({ state: "ok", message: "" }, response, 200);

                const fileOrFolderDeleteInput = await helperSrc.fileOrFolderDelete(`${helperSrc.PATH_ROOT}${helperSrc.PATH_FILE}input/${uniqueId}/`);

                if (typeof fileOrFolderDeleteInput !== "boolean") {
                    helperSrc.writeLog("Service.ts - api() - post(/api/extract-cancel) - fileOrFolderDelete()", fileOrFolderDeleteInput.toString());
                }
            } else if (this.cq.state(uniqueId).name === "running") {
                this.jobObject[uniqueId].isCancel = true;

                this.engineProcess.stdin.write(`${JSON.stringify({ action: "cancel", uniqueId })}\n`);

                helperSrc.responseBody({ state: "ok", message: "" }, response, 200);
            } else {
                delete this.jobObject[uniqueId];

                helperSrc.responseBody({ state: "ok", message: "" }, response, 200);

                const fileOrFolderDeleteOutput = await helperSrc.fileOrFolderDelete(
                    `${helperSrc.PATH_ROOT}${helperSrc.PATH_FILE}output/${uniqueId}/`
                );

                if (typeof fileOrFolderDeleteOutput !== "boolean") {
                    helperSrc.writeLog("Service.ts - api() - post(/api/extract-cancel) - fileOrFolderDelete()", fileOrFolderDeleteOutput.toString());
                }
            }
        });
    };
}
