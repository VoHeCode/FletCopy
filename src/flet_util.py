import flet.canvas as cv
from collections import namedtuple
import flet as ft


class SizeAwareControl(cv.Canvas):
    def __init__(self, content=None, resize_interval=100, on_resize=None, **kwargs):
        super().__init__(**kwargs)
        self.content = content
        self.resize_interval = resize_interval
        self.resize_callback = on_resize
        self.on_resize = self.__handle_canvas_resize
        self.size = namedtuple("size", ["width", "height"], defaults=[0, 0])

    def __handle_canvas_resize(self, e):
        """
        Called every resize_interval when the canvas is resized.
        If a resize_callback was given, it is called.
        """
        self.size = (int(e.width), int(e.height))
        self.update()
        if self.resize_callback:
            self.resize_callback(e)


# ---------------------------------------------------------------------------
# Beispiel / Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    def main(page: ft.Page):
        def handle_resize(e):
            c = e.control.content
            t = c.content
            t.value = f"{e.width} x {e.height}"
            page.update()

        s1 = SizeAwareControl(
            ft.Container(content=ft.Text("W x H"), bgcolor=ft.Colors.RED,  alignment=ft.alignment.center),
            on_resize=handle_resize, expand=2
        )
        s2 = SizeAwareControl(
            ft.Container(content=ft.Text("W x H"), bgcolor=ft.Colors.BLUE, alignment=ft.alignment.center),
            on_resize=handle_resize, expand=3
        )

        page.add(ft.Row([s1, s2], expand=True))

    ft.run(main)
