from fastapi import FastAPI
from pydantic import BaseModel
from openai_apps_sdk import AppServer, ui
from data import get_items

app = FastAPI()
server = AppServer(app)


class CarouselInput(BaseModel):
    query: str


@server.tool("show_carousel")
async def show_carousel(input: CarouselInput):
    items = get_items(input.query)

    cards = []
    for item in items:
        cards.append(
            ui.Card(
                title=item["title"],
                subtitle=item["subtitle"],
                body=item["description"],
                image=ui.Image(url=item["image"]),
                actions=[
                    ui.Button(
                        label=item["cta"]["label"],
                        value=item["cta"]["action"]
                    )
                ]
            )
        )

    return ui.Carousel(cards=cards)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
