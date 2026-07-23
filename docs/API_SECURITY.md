# API Security Policy

## Requirements
- Input Validation: Numbers verified via `input_validator.validate_decimal_amount()`.
- Payload Limits: Hard payload size ceiling of 1MB (`max_bytes=1_048_576`).
- Output DTO Filtering: All response models run through `output_sanitizer.sanitize_response_dto()`.
- Error Isolation: Internal exception stack traces are never exposed in REST responses.
