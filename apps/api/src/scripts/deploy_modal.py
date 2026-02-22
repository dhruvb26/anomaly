import modal

app = modal.App("my-agent-app")

sandbox_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "requests",
        "httpx",
        "pandas",
        "numpy",
        "matplotlib",
        "beautifulsoup4",
        "lxml",
    )
    .add_local_dir("data", "/seed-data", copy=True)
)


@app.function(image=sandbox_image)
def health_check():
    """Health check function to verify the app is running."""
    return {"status": "ok"}
