import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

test("TASK-202 real debug to trace, replay and provider divergence flow", async ({
  page,
  request,
}) => {
  const existingDraft = await (
    await request.get("/api/admin/config/draft")
  ).json();
  const draft = existingDraft.draft_json
    ? existingDraft
    : await (async () => {
        const bootstrap = JSON.parse(
          readFileSync("../bootstrap/initial-config.v1.json", "utf8"),
        );
        const response = await request.post("/api/admin/config/bootstrap", {
          data: { draft_json: bootstrap, expected_draft_hash: null },
        });
        expect(response.status()).toBe(201);
        return response.json();
      })();
  const releases = await (await request.get("/api/admin/releases")).json();
  const model = await (
    await request.post("/api/admin/model-configs", {
      data: {
        name: "TASK-202 localhost",
        version: "1",
        provider: "qwen",
        model: "qwen-local",
        base_url: "http://127.0.0.1:8011/v1",
        params_json: { temperature: 0 },
        timeout_seconds: 10,
        max_retries: 1,
        max_concurrency: 2,
        structured_output_mode: "json_object",
        credential_ref: "DASHSCOPE_API_KEY",
      },
    })
  ).json();
  const publishResponse = await request.post("/api/admin/releases", {
    data: {
      default_model_config_id: model.id,
      note: "TASK-202 browser E2E",
      expected_draft_hash: draft.draft_hash,
      expected_active_release_id: releases.active_release_id,
    },
  });
  expect(publishResponse.status()).toBe(201);
  const published = await publishResponse.json();
  expect(published.id).toBeTruthy();

  await page.goto("/");
  await page.getByRole("menuitem", { name: "单条调试" }).click();
  await page.getByPlaceholder("输入一句话").fill("我要练胸肌");
  await page.getByRole("button", { name: "识别" }).click();
  const run = page.getByText(/第 1 次/);
  await expect(run).toBeVisible();
  await run.click();
  await expect(page.getByText('"route": "training_business"')).toBeVisible();
  await expect(page.getByText('"final_prompt"')).toBeVisible();
  await expect(page.getByText('"raw_response"')).toBeVisible();
  await expect(page.getByText('"total": 18')).toBeVisible();

  await page.getByRole("button", { name: "刷新 Trace" }).click();
  const rows = page.getByRole("row");
  const originalRow = rows.filter({ hasText: "我要练胸肌" }).last();
  const traceList = await (
    await request.get("/api/admin/traces?limit=10")
  ).json();
  const originalTrace = traceList.items.find(
    (item: { source: string; input: string }) =>
      item.source === "debug" && item.input === "我要练胸肌",
  )?.trace_id as string | undefined;
  expect(originalTrace).toBeTruthy();
  await originalRow.getByRole("button", { name: "详情" }).click();
  await expect(page.getByText('"attempts"').last()).toBeVisible();
  const replayResponse = page.waitForResponse(
    (response) =>
      response.url().includes(`/api/admin/traces/${originalTrace}/replay`) &&
      response.request().method() === "POST",
  );
  await originalRow.getByRole("button", { name: "Replay" }).click();
  expect((await replayResponse).status()).toBe(200);
  await page.getByRole("button", { name: "刷新 Trace" }).click();

  const replay = await (await request.get(`/api/admin/traces?limit=10`)).json();
  const replayTrace = replay.items.find(
    (item: { parent_trace_id?: string }) =>
      item.parent_trace_id === originalTrace,
  );
  expect(replayTrace).toBeTruthy();
  const second = await (
    await request.post("/api/admin/debug/analyze", {
      data: { text: "我要练胸肌", repeat: 1 },
    })
  ).json();
  const secondTrace = second.runs[0].trace.trace_id;
  await page.getByPlaceholder("左 Trace ID").fill(originalTrace!);
  await page.getByPlaceholder("右 Trace ID").fill(secondTrace);
  await page.getByRole("button", { name: "对比" }).click();
  await expect(page.getByText('"provider_divergence": true')).toBeVisible();

  await page.getByRole("menuitem", { name: "服务状态" }).click();
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByRole("heading", { name: "就绪检查" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "最近 24 小时调用" }),
  ).toBeVisible();
  await page.getByText("查看状态详情", { exact: true }).click();
  await expect(page.locator(".status-json")).toContainText(
    `"active_release_id": ${published.id}`,
  );
  await expect(page.locator(".status-json")).toContainText(
    '"source": "runtime"',
  );
});
