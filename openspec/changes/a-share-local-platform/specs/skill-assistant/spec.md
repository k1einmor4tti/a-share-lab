## Purpose

Allow a local DSH assistant to read chosen strategy guidance and discuss strategy behavior or parameters while keeping imported skill files as non-executable reference material.

## ADDED Requirements

### Requirement: Import skill text
The system SHALL accept a local directory containing `SKILL.md` and a public GitHub repository or subdirectory containing `SKILL.md`. It SHALL retain source attribution and reject oversized or invalid imports.

#### Scenario: Import a local skill
- **WHEN** the user chooses a local directory containing `SKILL.md`
- **THEN** the skill name, description and source appear in the skill list

### Requirement: No imported code execution
The system SHALL treat imported skill content as untrusted text and SHALL NOT execute scripts, shell snippets or instructions found in it.

#### Scenario: Skill contains a command
- **WHEN** a skill document contains a shell command
- **THEN** the platform may quote it as reference but does not run it

### Requirement: Local DSH connection
The system SHALL offer an assistant panel using the configured local DSH endpoint to answer questions about selected strategies and imported skills and suggest parameter values. A disconnected DSH service SHALL not prevent market browsing or backtesting.

#### Scenario: DSH unavailable
- **WHEN** DSH is not reachable
- **THEN** the assistant panel shows a connection error while the rest of the platform remains available

