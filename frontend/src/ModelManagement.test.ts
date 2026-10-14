import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import ElementPlus from "element-plus";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import ModelManagement from "./ModelManagement.vue";
import { modelApi, type ManagedModel } from "./modelApi";

let wrapper: VueWrapper;
const model = (): ManagedModel => ({
  id: 1,
  model_uid: `mdl_${"a".repeat(64)}`,
  display_name: "通义千问 Plus",
  model_name: "qwen-plus",
  base_url: "https://example.com/v1",
  temperature: 0.1,
  top_p: 0.8,
  timeout_seconds: 30,
  max_retries: 1,
  max_concurrency: 4,
  enabled: true,
  credential_configured: true,
  credential_hint: "••••ABCD",
  last_verified_at: null,
  is_default: true,
  created_at: "2026-10-14T00:00:00",
  updated_at: "2026-10-14T00:00:00",
});

beforeEach(() => {
  vi.spyOn(modelApi, "list").mockResolvedValue({
    default_model_uid: model().model_uid,
    items: [model()],
  });
});

afterEach(() => {
  wrapper?.unmount();
  vi.restoreAllMocks();
});

async function render() {
  wrapper = mount(ModelManagement, {
    attachTo: document.body,
    global: { plugins: [ElementPlus], stubs: { teleport: true } },
  });
  await flushPromises();
}

it("shows product model cards without internal configuration fields", async () => {
  await render();

  expect(wrapper.text()).toContain("通义千问 Plus");
  expect(wrapper.text()).toContain("qwen-plus");
  expect(wrapper.text()).toContain("★ 默认");
  expect(wrapper.text()).toContain("••••ABCD");
  expect(wrapper.text()).not.toContain("Credential Ref");
  expect(wrapper.text()).not.toContain("Structured Output");
  expect(wrapper.text()).not.toContain("Fingerprint");
  expect(wrapper.text()).not.toContain("Release ID");
  expect(wrapper.text()).not.toContain("Qwen / OpenAI Compatible");
});

it("opens a friendly create form with masked API key input and no version field", async () => {
  await render();
  const add = wrapper.findAll("button").find((item) => item.text().includes("添加模型"));
  await add!.trigger("click");
  await flushPromises();

  expect(document.body.textContent).toContain("显示名称");
  expect(document.body.textContent).toContain("API 地址");
  expect(document.body.textContent).toContain("API Key");
  expect(document.body.textContent).toContain("验证连接");
  expect(document.body.textContent).toContain("模型名称");
  expect(document.body.textContent).not.toContain("模型服务");
  expect(document.body.textContent).not.toContain("Qwen / OpenAI Compatible");
  expect(document.body.textContent).not.toContain("Credential Ref");
  expect(document.body.textContent).not.toContain("创建模型版本");
  expect(document.body.querySelector('input[type="password"]')).not.toBeNull();
});

it("shows connection verification failures next to the action without clearing inputs", async () => {
  vi.spyOn(modelApi, "verifyNew").mockRejectedValue(
    new Error("认证失败，请检查 API Key"),
  );
  await render();
  const add = wrapper.findAll("button").find((item) => item.text().includes("添加模型"));
  await add!.trigger("click");
  await flushPromises();

  const baseUrl = wrapper.find('input[placeholder="例如：https://api.example.com/v1"]');
  const apiKey = wrapper.find('input[placeholder="输入 API Key"]');
  await baseUrl.setValue("https://api.example.com/v1");
  await apiKey.setValue("secret-value");
  const verifyButton = wrapper
    .findAll("button")
    .find((item) => item.text().includes("验证连接"));
  await verifyButton!.trigger("click");
  await flushPromises();

  expect(wrapper.text()).toContain("连接验证失败：认证失败，请检查 API Key");
  expect((baseUrl.element as HTMLInputElement).value).toBe(
    "https://api.example.com/v1",
  );
  expect((apiKey.element as HTMLInputElement).value).toBe("secret-value");
  expect(verifyButton!.attributes("disabled")).toBeUndefined();
});
