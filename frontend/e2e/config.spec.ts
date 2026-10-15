import { test, expect } from "@playwright/test";

test("real MySQL configuration: bootstrap, dynamic intent, publish, history and rollback", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByText("创建第一份 Draft")).toBeVisible();
  await page.getByRole("button", { name: "导入 Bootstrap 到 Draft" }).click();
  await expect(
    page.getByText("Bootstrap 已导入 Draft", { exact: false }),
  ).toBeVisible();
  const initial = await (await request.get("/api/admin/config/draft")).json();
  expect(
    (await (await request.get("/api/admin/releases")).json()).items,
  ).toHaveLength(0);

  await page.getByRole("tab", { name: "Model Config", exact: true }).click();
  await page.getByRole("button", { name: "创建模型版本" }).click();
  await expect(
    page.getByText("已创建 Qwen / 1", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Release", exact: true }).click();
  await page.getByRole("button", { name: "查看发布摘要" }).click();
  await expect(
    page.getByRole("dialog", { name: "确认发布新 Release" }),
  ).toBeVisible();
  await page
    .getByRole("textbox", { name: "发布说明", exact: true })
    .fill("browser baseline");
  await page.getByRole("button", { name: "确认发布并激活" }).click();
  await expect(page.getByText(/Release #\d+ 已发布并激活/)).toBeVisible();
  const first = (await (await request.get("/api/admin/releases")).json())
    .items[0];

  await page.getByRole("tab", { name: "Intent", exact: true }).click();
  await page.getByRole("button", { name: "新增 Intent" }).click();
  await page
    .getByRole("textbox", { name: "Intent 标识" })
    .fill("browser_intent");
  await page
    .getByRole("textbox", { name: "Intent 显示名称" })
    .fill("浏览器新增意图");
  await page.getByRole("combobox", { name: "Intent 所属 Route" }).click();
  await page.getByRole("option", { name: /social_chat/ }).click();
  await page.getByRole("textbox", { name: "Intent 说明" }).fill("在线新增");
  await page.getByRole("textbox", { name: "典型用户说法" }).fill("新称呼");
  await page.getByRole("button", { name: "添加", exact: true }).click();
  await page.getByRole("button", { name: "保存 Intent" }).click();
  await page.getByRole("tab", { name: "Enum/Alias", exact: true }).click();
  const enums = structuredClone(initial.draft_json.enums);
  enums.body_part.push({
    canonical: "browser_part",
    display: "新部位",
    aliases: ["新部位别名"],
    enabled: true,
  });
  await page
    .getByRole("textbox", { name: "Enums JSON" })
    .fill(JSON.stringify(enums));
  await expect(
    page.getByRole("button", { name: "Prompt 预览", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "保存配置", exact: true }).click();
  await expect(page.getByText("配置已保存")).toBeVisible();
  await page.getByRole("button", { name: "校验", exact: true }).click();
  await expect(page.getByText(/校验通过：/)).toBeVisible();
  await page.getByRole("button", { name: "Prompt 预览", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "Prompt 预览" });
  await expect(preview).toContainText("browser_intent");
  await preview.getByRole("button", { name: "Close this dialog" }).click();
  await page.getByRole("tab", { name: "Release", exact: true }).click();
  await page.getByRole("button", { name: "查看发布摘要" }).click();
  await expect(
    page.getByRole("dialog", { name: "确认发布新 Release" }),
  ).toContainText("intents");
  await page
    .getByRole("textbox", { name: "发布说明", exact: true })
    .fill("dynamic config");
  await page.getByRole("button", { name: "确认发布并激活" }).click();
  await expect(page.getByText(/Release #\d+ 已发布并激活/)).toBeVisible();
  const second = (await (await request.get("/api/admin/releases")).json())
    .items[0];
  expect(second.config_snapshot_hash).not.toBe(first.config_snapshot_hash);
  const historical = await (
    await request.get(`/api/admin/releases/${first.id}`)
  ).json();
  expect(
    historical.snapshot_json.intents.some(
      (i: { name: string }) => i.name === "browser_intent",
    ),
  ).toBe(false);

  const baselineRow = page
    .getByRole("row")
    .filter({ hasText: "browser baseline" });
  await baselineRow.getByRole("button", { name: "从此版本创建 Draft" }).click();
  await page
    .getByRole("dialog", { name: "从历史 Release 创建 Draft" })
    .getByRole("button", { name: "OK", exact: true })
    .click();
  await expect(page.getByText(/已从 Release #\d+ 创建 Draft/)).toBeVisible();
  await page.getByRole("button", { name: "查看发布摘要" }).click();
  await page
    .getByRole("textbox", { name: "发布说明", exact: true })
    .fill("rollback baseline");
  await page.getByRole("button", { name: "确认发布并激活" }).click();
  await expect(page.getByText(/Release #\d+ 已发布并激活/)).toBeVisible();
  const history = await (await request.get("/api/admin/releases")).json();
  expect(history.items).toHaveLength(3);
  expect(history.active_release_id).toBe(history.items[0].id);
  expect(history.items[0].id).not.toBe(first.id);
  expect(history.items[0].release_fingerprint).toBe(first.release_fingerprint);
  expect(errors).toEqual([]);
});
