from datetime import timedelta

from app.config.loader import (
    PROJECT_ROOT,
    AppConfig,
    IngestionSection,
    MCPConfig,
    MCPServerSpec,
    VaultSection,
    WikiSection,
    load_config,
    load_mcp_config,
    load_user_mcp_config,
    save_mcp_config,
)


def test_blank_vault_path_is_unset() -> None:
    assert VaultSection(path="   ").path_abs is None


def test_project_root_is_the_server_directory() -> None:
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert (PROJECT_ROOT / "configs" / "app.yaml").is_file()


def test_wiki_directory_is_normalized() -> None:
    assert WikiSection(directory="/_omn_wiki/").directory == "_omn_wiki"
    assert "_omn_wiki" in VaultSection().excluded_dirs


def test_custom_wiki_directory_is_excluded_from_vault_scan() -> None:
    cfg = AppConfig(wiki={"directory": "generated-wiki"}, vault={"excluded_dirs": ["cache"]})

    assert "cache" in cfg.vault.excluded_dirs
    assert "generated-wiki" in cfg.vault.excluded_dirs


def test_ingestion_defaults_enable_pdf_monster_auto() -> None:
    cfg = AppConfig()

    assert cfg.ingestion.pdf_backend == "auto"
    assert cfg.ingestion.pdf_ocr == "auto"
    assert cfg.ingestion.pdf_ocr_lang == "kor+eng"


def test_ingestion_config_overrides_roundtrip(tmp_path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text(
        "\n".join(
            [
                "ingestion:",
                "  pdf_backend: pypdf",
                "  pdf_ocr: never",
                "  pdf_ocr_lang: eng",
                "  pdf_ocr_threshold: 120",
                "  pdf_render_dpi: 96",
                "  pdf_max_page_text_chars: 5000",
                "  pdf_visual_review_image_area: 2500",
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_config(path)

    assert cfg.ingestion == IngestionSection(
        pdf_backend="pypdf",
        pdf_ocr="never",
        pdf_ocr_lang="eng",
        pdf_ocr_threshold=120,
        pdf_render_dpi=96,
        pdf_max_page_text_chars=5000,
        pdf_visual_review_image_area=2500,
    )


def test_stdio_mcp_spec_expands_environment(monkeypatch) -> None:
    monkeypatch.setenv("OMN_MCP_BIN", "uvx")
    monkeypatch.setenv("OMN_MCP_TOKEN", "secret")

    spec = MCPServerSpec(
        name="law",
        transport="stdio",
        command="$OMN_MCP_BIN",
        args=["server", "$OMN_MCP_TOKEN"],
        cwd="$HOME",
        env={"TOKEN": "$OMN_MCP_TOKEN"},
    ).to_adapter_spec()

    assert spec["transport"] == "stdio"
    assert spec["command"] == "uvx"
    assert spec["args"] == ["server", "secret"]
    assert spec["env"] == {"TOKEN": "secret"}
    assert "$HOME" not in spec["cwd"]


def test_http_mcp_spec_maps_to_streamable_http(monkeypatch) -> None:
    monkeypatch.setenv("OMN_MCP_TOKEN", "secret")

    spec = MCPServerSpec(
        name="remote",
        transport="http",
        url="https://example.test/mcp",
        headers={"Authorization": "Bearer $OMN_MCP_TOKEN"},
        timeout=5,
        sse_read_timeout=30,
        terminate_on_close=True,
    ).to_adapter_spec()

    assert spec["transport"] == "streamable_http"
    assert spec["url"] == "https://example.test/mcp"
    assert spec["headers"] == {"Authorization": "Bearer secret"}
    assert spec["timeout"] == timedelta(seconds=5)
    assert spec["sse_read_timeout"] == timedelta(seconds=30)
    assert spec["terminate_on_close"] is True


def test_save_mcp_config_roundtrips(tmp_path) -> None:
    path = tmp_path / "mcp.yaml"
    config = MCPConfig(
        servers={
            "web_search": MCPServerSpec(
                name="web_search",
                transport="stdio",
                command="uvx",
                args=["mcp-server-web-search"],
                env={"TOKEN": "$WEB_TOKEN"},
            )
        }
    )

    save_mcp_config(config, path)
    loaded = load_mcp_config(path)

    assert set(loaded.servers) == {"web_search"}
    assert loaded.servers["web_search"].command == "uvx"
    assert loaded.servers["web_search"].args == ["mcp-server-web-search"]


def test_default_mcp_config_bundles_law_and_web_search() -> None:
    loaded = load_mcp_config(PROJECT_ROOT / "configs/mcp_servers.yaml")

    assert loaded.servers["korean_law"].args == ["korean-law-mcp"]
    assert loaded.servers["web_search"].args == ["duckduckgo-mcp-server"]
    assert loaded.servers["web_search"].env["DDG_REGION"] == "kr-kr"


def test_user_mcp_config_seeds_from_builtin_config(tmp_path) -> None:
    base_path = tmp_path / "base.yaml"
    user_path = tmp_path / "user" / "mcp_servers.yaml"
    base_config = MCPConfig(
        servers={
            "korean_law": MCPServerSpec(name="korean_law", command="uvx", args=["korean-law-mcp"]),
            "web_search": MCPServerSpec(name="web_search", command="uvx", args=["duckduckgo-mcp-server"]),
        }
    )
    save_mcp_config(base_config, base_path)

    loaded = load_user_mcp_config(base_path, user_path)

    assert user_path.exists()
    assert set(loaded.servers) == {"korean_law", "web_search"}
    assert load_mcp_config(user_path).servers["web_search"].args == ["duckduckgo-mcp-server"]
