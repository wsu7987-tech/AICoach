import { afterEach, describe, expect, it, vi } from "vitest";
import { configApi, ConfigApiError, type PublishSummary } from "./configApi";

afterEach(() => vi.unstubAllGlobals());
describe("Admin API client contract", () => {
  it.each([null, 1])(
    "sends both review tokens with active=%s",
    async (active) => {
      const fetch = vi
        .fn()
        .mockResolvedValue({ ok: true, json: async () => ({ id: 2 }) });
      vi.stubGlobal("fetch", fetch);
      const summary = {
        default_model_config_id: 3,
        draft_hash: "hash",
        active_release_id: active,
      } as PublishSummary;
      await configApi.publish(summary, "reviewed");
      expect(fetch).toHaveBeenCalledWith(
        "/api/admin/releases",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            default_model_config_id: 3,
            note: "reviewed",
            expected_draft_hash: "hash",
            expected_active_release_id: active,
          }),
        }),
      );
    },
  );
  it("preserves field issues and conflict codes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({
          error_code: "CONFIG_INVALID",
          message: "invalid",
          issues: [{ field: "routes", message: "seven required" }],
        }),
      }),
    );
    const error = await configApi.validate().catch((e) => e);
    expect(error).toBeInstanceOf(ConfigApiError);
    expect(error.issues[0].field).toBe("routes");
  });
  it("bootstrap calls only explicit Draft import", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetch);
    await configApi.bootstrap({} as never);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/admin/config/bootstrap");
  });
});
