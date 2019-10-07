# auto-maintenance

A Serverless Framework application in support of this serverless, email-based document text extraction solution.

![Solution Architecture](.docs/auto-maintenance-record-processing.png)

A full overview of the solution is available on my [blog](https://bradcod.es/post/building-a-serverless-email-document-extraction-solution-with-aws-textract-part-1-overview/).

## Dependencies

### Assumptions

- Valid, working `npm` in `PATH`
- Valid, working `serverless`|`sls` in `PATH`
- Valid, working `python` in `PATH` (this is some rev of Python 3.7)

## Usage

### Setup

Copy `config.yml.example` to `config.yml` and configure according to comments in the file.

### Deploying

```bash
$ npm install
$ export AWS_PROFILE=my-profile
$ export AWS_REGION=us-east-2    # or whatever region suits you
$ serverless deploy
```
