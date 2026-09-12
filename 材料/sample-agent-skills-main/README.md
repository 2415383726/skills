# Agentic IDE Skills

A collection of skills for agentic IDEs like [Kiro](https://kiro.dev) and [Claude Code](https://docs.anthropic.com/en/docs/claude-code). They enable agents to natively read and write Office files and PDFs.

## Included Skills

| Skill | Description | Formats |
|-------|-------------|---------|
| `office-excel` | Read and write spreadsheets | `.xlsx` |
| `office-word` | Read and write Word documents | `.docx` |
| `office-powerpoint` | Read and write presentations | `.pptx` |
| `pdf-to-markdown` | Convert between PDF and Markdown | `.pdf` |

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — Python dependencies are automatically installed via `uv run`.

## Installation

Clone the repository into your IDE's skills folder:

```bash
# Kiro
git clone https://github.com/aws-samples/sample-agent-skills.git ~/.kiro/skills

# Claude Code
git clone https://github.com/aws-samples/sample-agent-skills.git ~/.claude/skills
```

If you already have a skills folder with existing content, you can copy only the ones you need:

```bash
cp -r office-excel ~/.kiro/skills/
cp -r office-word ~/.kiro/skills/
cp -r office-powerpoint ~/.kiro/skills/
cp -r pdf-to-markdown ~/.kiro/skills/
```

## Quick Usage

Once installed, the agent uses them automatically when you ask it to work with these formats. Some examples:

```
"Read sales.xlsx and give me a summary"
"Convert this PDF to markdown"
"Create a presentation with this data"
"Generate a Word document with the report"
```

## License

This project is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.

## Third-Party Licenses

See [THIRD-PARTY-LICENSES](THIRD-PARTY-LICENSES) for dependency attribution and license details. Note that the `pdf-to-markdown` skill depends on PyMuPDF which is AGPL-3.0 licensed.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## Contributing

See [CONTRIBUTING](CONTRIBUTING.md) for more information.
