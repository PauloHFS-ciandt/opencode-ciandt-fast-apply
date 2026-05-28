import type { Plugin } from "@opencode-ai/plugin"
import { tool } from "@opencode-ai/plugin"
import { resolve, isAbsolute } from "path"
import { existsSync } from "fs"
import { readFile, writeFile } from "fs/promises"

const EXISTING_CODE_MARKER = "// ... existing code ..."
const READONLY_AGENTS = ["plan", "explore"]

const PROXY_URL = process.env.FLOW_LITELLM_PROXY
  ?? "https://flow.ciandt.com/flow-llm-proxy"
const API_KEY = process.env.FLOW_API_KEY ?? ""
const MODEL = process.env.FAST_APPLY_MODEL ?? "anthropic.claude-4-5-haiku"
const ENABLED = process.env.FAST_APPLY_ENABLED !== "false"

const MERGE_SYSTEM_PROMPT = `You are a code merge specialist. You receive an original file and a partial edit that uses "${EXISTING_CODE_MARKER}" markers to represent unchanged sections.

Your task:
1. Replace each "${EXISTING_CODE_MARKER}" marker with the corresponding unchanged section from the original file.
2. Apply the new/changed code exactly as provided in the edit.
3. Preserve all indentation, whitespace, and formatting from both the original and the edit.

Rules:
- Return ONLY the complete merged file content.
- No explanations, no markdown fences, no commentary, no prefixes.
- Do not add or remove any code beyond what the edit specifies.
- If the edit starts or ends with a marker, include all original code before/after the edited section.`

let stats = { calls: 0, filesEdited: 0, tokensIn: 0, tokensOut: 0 }

function stripMarkdownFences(code: string): string {
  const trimmed = code.trim()
  const lines = trimmed.split("\n")
  if (lines.length < 3) return code
  if (/^```[\w-]*$/.test(lines[0]) && /^```$/.test(lines[lines.length - 1])) {
    return lines.slice(1, -1).join("\n")
  }
  return code
}

function detectMarkerLeakage(original: string, merged: string): boolean {
  const originalHadMarker = original.includes(EXISTING_CODE_MARKER)
  return !originalHadMarker && merged.includes(EXISTING_CODE_MARKER)
}

function detectCatastrophicTruncation(original: string, merged: string): { charLoss: number; lineLoss: number; triggered: boolean } {
  const originalLines = original.split("\n").length
  const mergedLines = merged.split("\n").length
  const charLoss = (original.length - merged.length) / original.length
  const lineLoss = (originalLines - mergedLines) / originalLines
  return { charLoss, lineLoss, triggered: charLoss > 0.6 && lineLoss > 0.5 }
}

function computeDiff(original: string, merged: string): { added: number; removed: number } {
  const origLines = new Set(original.split("\n"))
  const mergedLines = new Set(merged.split("\n"))
  let added = 0, removed = 0
  for (const line of mergedLines) if (!origLines.has(line)) added++
  for (const line of origLines) if (!mergedLines.has(line)) removed++
  return { added, removed }
}

async function callMergeModel(original: string, codeEdit: string, instructions: string): Promise<{ content: string; tokensIn: number; tokensOut: number }> {
  const resp = await fetch(`${PROXY_URL}/v1/chat/completions`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: MODEL,
      messages: [
        { role: "system", content: MERGE_SYSTEM_PROMPT },
        {
          role: "user",
          content: `<original>\n${original}\n</original>\n\n<edit>\n${codeEdit}\n</edit>\n\nInstructions: ${instructions}\n\nReturn the complete merged file:`,
        },
      ],
      temperature: 0,
      max_tokens: Math.max(original.split("\n").length * 20, 4096),
    }),
  })

  if (!resp.ok) {
    const body = await resp.text()
    throw new Error(`Proxy returned ${resp.status}: ${body.slice(0, 200)}`)
  }

  const data = await resp.json() as {
    choices: { message: { content: string } }[]
    usage?: { prompt_tokens: number; completion_tokens: number }
  }

  const content = data.choices?.[0]?.message?.content ?? ""
  return {
    content: stripMarkdownFences(content),
    tokensIn: data.usage?.prompt_tokens ?? 0,
    tokensOut: data.usage?.completion_tokens ?? 0,
  }
}

export const FastApplyPlugin: Plugin = async () => {
  if (!ENABLED) return {}

  const fastApplyTool = tool({
    description: `Edit existing files using partial code snippets with "${EXISTING_CODE_MARKER}" markers. Prefer this over edit for files >30 lines with scattered changes. Use native edit for small exact replacements. Use write for new files.\n\nFORMAT:\n${EXISTING_CODE_MARKER}\nFIRST_EDIT\n${EXISTING_CODE_MARKER}\nSECOND_EDIT\n${EXISTING_CODE_MARKER}\n\nRULES: Always wrap changes with markers at start AND end. Include 1-2 context lines around each edit. Write specific instructions. Preserve indentation. Batch edits to same file.`,
    args: {
      target_file: tool.schema.string().describe("Absolute or relative path to the file to modify"),
      instructions: tool.schema.string().describe("Brief first-person description of the change, e.g. 'I am adding error handling to the login function'"),
      code_edit: tool.schema.string().describe(`Code changes with "${EXISTING_CODE_MARKER}" markers for unchanged sections`),
    },
    async execute(args, context) {
      if (!API_KEY) {
        return `Error: FLOW_API_KEY environment variable not set. fast_apply requires the CI&T proxy API key.\nSet it with: export FLOW_API_KEY="your-jwt-token"`
      }

      const agent = context?.agent ?? ""
      if (READONLY_AGENTS.includes(agent)) {
        return `Error: fast_apply is not available in ${agent} mode. Use this tool only from implementation agents.`
      }

      const dir = context?.directory ?? process.cwd()
      const filePath = isAbsolute(args.target_file) ? args.target_file : resolve(dir, args.target_file)

      if (!existsSync(filePath)) {
        return `Error: File not found: ${filePath}\nUse the write tool to create new files.`
      }

      const original = await readFile(filePath, "utf-8")
      const normalizedEdit = stripMarkdownFences(args.code_edit)
      const hasMarkers = normalizedEdit.includes(EXISTING_CODE_MARKER)
      const originalLineCount = original.split("\n").length

      if (!hasMarkers && originalLineCount > 10) {
        return `Error: Missing "${EXISTING_CODE_MARKER}" markers in code_edit.\nFor files >10 lines, you MUST use markers to indicate unchanged sections.\nUse the native edit tool for small exact replacements.`
      }

      const startTime = Date.now()
      let result: { content: string; tokensIn: number; tokensOut: number }

      try {
        result = await callMergeModel(original, normalizedEdit, args.instructions)
      } catch (err: any) {
        return `Error: Fast Apply merge failed: ${err.message}\nFallback: use the native edit tool to apply changes manually.`
      }

      const merged = result.content
      const elapsed = Date.now() - startTime

      if (!merged || merged.trim().length === 0) {
        return `Error: Merge model returned empty output.\nFallback: use the native edit tool to apply changes manually.`
      }

      if (hasMarkers && detectMarkerLeakage(original, merged)) {
        return `Error: Marker leakage detected — merge model left "${EXISTING_CODE_MARKER}" in output instead of expanding it.\nThe file was NOT modified.\nFallback: use the native edit tool to apply changes manually.`
      }

      if (hasMarkers) {
        const trunc = detectCatastrophicTruncation(original, merged)
        if (trunc.triggered) {
          return `Error: Catastrophic truncation detected — merged file lost ${Math.round(trunc.charLoss * 100)}% characters and ${Math.round(trunc.lineLoss * 100)}% lines.\nOriginal: ${originalLineCount} lines (${original.length} chars)\nMerged: ${merged.split("\n").length} lines (${merged.length} chars)\nThe file was NOT modified.\nFallback: use the native edit tool to apply changes manually.`
        }
      }

      await writeFile(filePath, merged, "utf-8")

      const diff = computeDiff(original, merged)
      stats.calls++
      stats.filesEdited++
      stats.tokensIn += result.tokensIn
      stats.tokensOut += result.tokensOut

      return `Applied edit to ${args.target_file} — +${diff.added}/-${diff.removed} lines | ${elapsed}ms | model: ${MODEL}`
    },
  })

  return {
    tool: {
      fast_apply: fastApplyTool,
    },

    config: async (opencodeConfig: any) => {

      opencodeConfig.command ??= {}
      opencodeConfig.command["fast-apply"] = {
        template: "",
        description: "Show Fast Apply plugin status and stats",
      }
    },

    "command.execute.before": async (input: any, output: any) => {
      if (input.command === "fast-apply") {
        output.parts.push({
          type: "text" as const,
          text: [
            "# Fast Apply Status",
            "",
            `Enabled: ${ENABLED}`,
            `Model: ${MODEL}`,
            `Proxy: ${PROXY_URL}`,
            `API Key: ${API_KEY ? "set" : "missing"}`,
            "",
            "## Session Stats",
            `Calls: ${stats.calls}`,
            `Files edited: ${stats.filesEdited}`,
            `Tokens in: ${stats.tokensIn.toLocaleString()}`,
            `Tokens out: ${stats.tokensOut.toLocaleString()}`,
            "",
            "## Usage",
            'Agents automatically use `fast_apply` for large scattered edits.',
            "Native `edit` is preferred for small exact replacements.",
            "`write` is used for new files.",
          ].join("\n"),
        })
      }
    },

    "experimental.chat.system.transform": async (_input: any, output: any) => {
      output.system.push(
        `## Fast Apply\nPrefer fast_apply over edit for modifying existing files >30 lines with scattered changes. Use native edit for small exact replacements (<5 lines). Use write for new files.\nFormat: wrap unchanged code with "${EXISTING_CODE_MARKER}" markers. Include 1-2 context lines around each edit for precise anchoring.`
      )
    },
  }
}

export default FastApplyPlugin
