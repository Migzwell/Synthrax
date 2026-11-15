"""NiceGUI screens."""
from nicegui import ui

from .common import Site, header, event_log, page_style


def build(site: Site) -> None:
    """Register this site's screen at '/'. Call once, before ui.run_with()."""
    from . import carehome, gp, pharmacy
    screens = {"carehome": carehome.build, "gp": gp.build, "pharmacy": pharmacy.build}

    @ui.page("/")
    def page():
        page_style(site)
        header(site)
        screens[site.node_id](site)
        event_log(site)
