# Security Policy

## Supported Versions

We release patches for security vulnerabilities. Currently supported versions:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Reporting a Vulnerability

We take the security of DarkstarAIC seriously. If you discover a security vulnerability, please follow these steps:

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via one of the following methods:

1. **Email**: Contact the maintainer directly at the email associated with their GitHub account
2. **GitHub Security Advisory**: Use GitHub's [private vulnerability reporting](https://github.com/joemurrell/darkstar/security/advisories/new) feature

### What to Include

Please include the following information in your report:

- Type of vulnerability
- Full description of the vulnerability
- Steps to reproduce the issue
- Potential impact
- Suggested fix (if you have one)

### What to Expect

- **Acknowledgment**: We will acknowledge receipt of your vulnerability report within 48 hours
- **Investigation**: We will investigate the issue and determine its severity
- **Updates**: We will keep you informed about the progress toward fixing the vulnerability
- **Resolution**: Once the vulnerability is fixed, we will notify you and publicly acknowledge your responsible disclosure (unless you prefer to remain anonymous)

### Security Best Practices for Users

When deploying DarkstarAIC:

1. **Environment Variables**: Never commit API keys, tokens, or sensitive credentials to version control
2. **Bot Permissions**: Grant only the minimum required Discord permissions
3. **API Keys**: Regularly rotate OpenAI API keys and Discord bot tokens
4. **Access Control**: Restrict bot usage to trusted Discord servers
5. **Logging**: Regularly review logs for suspicious activity
6. **Updates**: Keep dependencies up to date to patch known vulnerabilities

### Disclosure Policy

- We will work with you to understand and resolve the issue quickly
- We will credit researchers who responsibly disclose vulnerabilities (unless they wish to remain anonymous)
- We request that you do not publicly disclose the vulnerability until we have had a reasonable amount of time to address it

## Known Security Considerations

- **API Keys**: The bot requires API keys that must be kept secure
- **PDF Content**: Uploaded PDFs to OpenAI Assistants are stored on OpenAI's servers
- **Discord Permissions**: The bot requires message content intent which allows reading message content
- **Rate Limiting**: Consider implementing rate limiting for production deployments to prevent abuse

Thank you for helping keep DarkstarAIC and its users safe!
