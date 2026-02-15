class ContextExtractor:

    def extract_context(self, file_content, keyword, window=40):
        lines = file_content.split("\n")

        for i, line in enumerate(lines):
            if keyword.lower() in line.lower():
                start = max(i - window, 0)
                end = min(i + window, len(lines))
                return "\n".join(lines[start:end])

        return file_content[:1500]
