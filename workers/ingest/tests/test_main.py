from workers.ingest.main import main


def test_main_runs() -> None:
    # Should not raise
    main()
