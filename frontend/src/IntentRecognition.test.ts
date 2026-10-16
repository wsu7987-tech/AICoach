import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import ElementPlus from "element-plus";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import IntentRecognition from "./IntentRecognition.vue";
import { analyzeIntent, IntentApiError } from "./intentApi";
import { modelApi } from "./modelApi";

vi.mock("./intentApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./intentApi")>();
  return { ...actual, analyzeIntent: vi.fn() };
});

const modelUid = `mdl_${"a".repeat(64)}`;
let wrapper: VueWrapper;

beforeEach(() => {
  vi.spyOn(modelApi, "list").mockResolvedValue({
    default_model_uid: modelUid,
    items: [
      {
        id: 1,
        model_uid: modelUid,
        display_name: "DeepSeek Flash",
        model_name: "deepseek-flash",
        base_url: "https://api.example.com/v1",
        temperature: 0.1,
        top_p: 0.8,
        enable_thinking: false,
        timeout_seconds: 30,
        max_retries: 1,
        max_concurrency: 4,
        enabled: true,
        credential_configured: true,
        credential_hint: "••••1234",
        last_verified_at: null,
        is_default: true,
        created_at: "2026-10-14T00:00:00",
        updated_at: "2026-10-14T00:00:00",
      },
    ],
  });
});

afterEach(() => {
  wrapper?.unmount();
  vi.restoreAllMocks();
});

async function render() {
  wrapper = mount(IntentRecognition, {
    attachTo: document.body,
    global: { plugins: [ElementPlus] },
  });
  await flushPromises();
}

it("submits the selected model and renders product result fields", async () => {
  vi.mocked(analyzeIntent).mockResolvedValue({
    request_id: "request-1",
    text: "我想减脂",
    route: "training_business",
    intents: [{ name: "fat_loss", zh: "减脂训练", confidence: 0.94 }],
    slots: [
      {
        name: "goal",
        zh: "目标",
        value: "减脂",
        start: 2,
        end: 4,
        confidence: 0.9,
      },
    ],
    risk: null,
    need_clarification: false,
    clarification: null,
  });
  await render();

  await wrapper.find("textarea").setValue("我想减脂");
  const submit = wrapper
    .findAll("button")
    .find((button) => button.text().includes("开始识别"));
  await submit!.trigger("click");
  await flushPromises();

  expect(analyzeIntent).toHaveBeenCalledWith({
    text: "我想减脂",
    context: {},
    model_uid: modelUid,
  });
  expect(wrapper.text()).toContain("训练业务");
  expect(wrapper.text()).toContain("training_business");
  expect(wrapper.text()).toContain("减脂训练");
  expect(wrapper.text()).toContain("94%");
  expect(wrapper.text()).toContain("目标");
  expect(wrapper.text()).toContain("减脂");
  expect(wrapper.text()).not.toContain("request-1");
});

it("keeps input and shows a readable provider failure", async () => {
  vi.mocked(analyzeIntent).mockRejectedValue(
    new IntentApiError("MODEL_PROVIDER_ERROR", "provider failed", 502),
  );
  await render();

  await wrapper.find("textarea").setValue("保留这句话");
  const submit = wrapper
    .findAll("button")
    .find((button) => button.text().includes("开始识别"));
  await submit!.trigger("click");
  await flushPromises();

  expect((wrapper.find("textarea").element as HTMLTextAreaElement).value).toBe(
    "保留这句话",
  );
  expect(wrapper.text()).toContain(
    "模型服务调用失败，请检查 API 地址、API Key 和模型名称。",
  );
});
