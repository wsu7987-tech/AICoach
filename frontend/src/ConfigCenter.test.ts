import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import ElementPlus from "element-plus";
import ConfigCenter from "./ConfigCenter.vue";
import bootstrap from "../../bootstrap/initial-config.v1.json";
import {
  configApi,
  ConfigApiError,
  type Draft,
  type DraftJson,
} from "./configApi";

let wrapper: VueWrapper;
const draft = (): Draft => ({
  draft_json: structuredClone(bootstrap) as DraftJson,
  draft_hash: "hash",
  updated_at: null,
});
beforeEach(() => {
  vi.spyOn(configApi, "draft").mockResolvedValue(draft());
  vi.spyOn(configApi, "models").mockResolvedValue([]);
  vi.spyOn(configApi, "releases").mockResolvedValue({
    items: [],
    active_release_id: null,
  });
});
afterEach(() => {
  wrapper?.unmount();
  vi.restoreAllMocks();
});
async function render() {
  wrapper = mount(ConfigCenter, { global: { plugins: [ElementPlus] } });
  await flushPromises();
}
function button(label: string) {
  return wrapper.findAll("button").find((b) => b.text() === label)!;
}

it("guides explicit bootstrap import without publishing", async () => {
  vi.mocked(configApi.draft).mockResolvedValue({
    draft_json: null,
    draft_hash: null,
    updated_at: null,
  });
  const importing = vi.spyOn(configApi, "bootstrap").mockResolvedValue(draft());
  const publishing = vi.spyOn(configApi, "publish");
  await render();
  expect(wrapper.text()).toContain("创建第一份 Draft");
  expect(importing).not.toHaveBeenCalled();
  await button("导入 Bootstrap 到 Draft").trigger("click");
  await flushPromises();
  expect(importing).toHaveBeenCalledTimes(1);
  expect(publishing).not.toHaveBeenCalled();
});

it("blocks preview of unsaved edits and saves against the loaded Draft hash", async () => {
  const save = vi.spyOn(configApi, "save").mockResolvedValue(draft());
  await render();
  await wrapper
    .get('input[aria-label="training_business 中文名"]')
    .setValue("新训练名");
  expect(button("Prompt 预览").attributes("disabled")).toBeDefined();
  await button("保存 Draft").trigger("click");
  await flushPromises();
  expect(save).toHaveBeenCalledWith(
    expect.objectContaining({
      routes: expect.arrayContaining([
        expect.objectContaining({ zh: "新训练名" }),
      ]),
    }),
    "hash",
  );
  expect(wrapper.text()).toContain("Draft 已保存");
});

it("shows server field errors while retaining edits", async () => {
  vi.spyOn(configApi, "save").mockRejectedValue(
    new ConfigApiError("CONFIG_INVALID", "配置错误", [
      { field: "intents", message: "alias conflict" },
    ]),
  );
  await render();
  await wrapper
    .get('input[aria-label="training_business 中文名"]')
    .setValue("新训练名");
  await button("保存 Draft").trigger("click");
  await flushPromises();
  expect(wrapper.text()).toContain("intents：alias conflict");
  expect(wrapper.text()).toContain("未保存");
  expect(
    (
      wrapper.get('input[aria-label="training_business 中文名"]')
        .element as HTMLInputElement
    ).value,
  ).toBe("新训练名");
});
