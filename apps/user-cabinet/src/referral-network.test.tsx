import React from "react";
import {render,screen,cleanup} from "@testing-library/react";
import {afterEach,expect,it} from "vitest";
import {ReferralNetwork} from "./referral-network";
afterEach(cleanup);
it("shows anonymous network and explicit truncation",()=>{
 render(<ReferralNetwork data={{nodes:[{id:"root",parent:null,level:0},{id:"child",parent:"root",level:1}],level_counts:[{level:1,count:1}],truncated:true}}/>);
 expect(screen.getByRole("img",{name:"Обезличенный граф реферальной сети"})).toBeTruthy();
 expect(screen.getByText("Участник 1")).toBeTruthy();
 expect(screen.getByText(/сеть продолжается/)).toBeTruthy();
});
it("shows root without inventing invitees",()=>{
 render(<ReferralNetwork data={{nodes:[{id:"root",parent:null,level:0}],level_counts:[{level:1,count:0}],truncated:false}}/>);
 expect(screen.getByText("Вы")).toBeTruthy();
 expect(screen.queryByText(/^Участник \d+$/)).toBeNull();
 expect(screen.queryByText(/сеть продолжается/)).toBeNull();
});
